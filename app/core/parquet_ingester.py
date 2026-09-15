import polars as pl
import os
import re
import logging
import time
import json
import duckdb
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

class ParquetIngester:
    """
    Enterprise-grade ingestion layer for 1M+ row datasets.
    Safely streams large CSVs or reads massive Excel files using memory-efficient Calamine,
    and writes them out as chunked, compressed Parquet files for DuckDB querying.
    """
    @staticmethod
    def _validate_csv_headers(columns: list[str]) -> bool:
        """
        Validate whether auto-detected CSV headers look like real column names
        or like data values that Polars mistakenly promoted to headers.
        
        Uses a combined 2-of-4 signal scoring approach to avoid false positives
        on legitimate edge cases (e.g. a single verbose column, year-named columns).
        
        Returns True if headers look legitimate, False if they look like data.
        """
        if not columns:
            return True
        
        signals_fired = 0
        
        # Signal 1: Any column name > 60 chars (data values like addresses, descriptions)
        long_cols = [c for c in columns if len(c) > 60]
        if long_cols:
            signals_fired += 1
            logger.debug(f"CSV header signal 1 (excessive length): {len(long_cols)} columns exceed 60 chars")
        
        # Signal 2: > 50% of columns are purely numeric strings (data row, not headers)
        numeric_cols = [c for c in columns if c.replace('.', '', 1).replace('-', '', 1).isdigit()]
        if len(numeric_cols) > len(columns) * 0.5:
            signals_fired += 1
            logger.debug(f"CSV header signal 2 (numeric dominance): {len(numeric_cols)}/{len(columns)} columns are numeric")
        
        # Signal 3: Average underscores per column > 3 (Polars normalizes spaces in data to underscores)
        avg_underscores = sum(c.count('_') for c in columns) / max(len(columns), 1)
        if avg_underscores > 3:
            signals_fired += 1
            logger.debug(f"CSV header signal 3 (underscore density): avg {avg_underscores:.1f} underscores/column")
        
        # Signal 4: Any column matches auto-generated naming patterns (library already struggled)
        auto_pattern = [c for c in columns if re.match(r'^(column|unnamed|none)_\d+$', c, re.IGNORECASE)]
        if auto_pattern:
            signals_fired += 1
            logger.debug(f"CSV header signal 4 (auto-pattern): {auto_pattern}")
        
        if signals_fired >= 2:
            logger.warning(
                f"CSV header validation FAILED ({signals_fired}/4 signals fired). "
                f"Detected headers look like data values, not column names. "
                f"Headers: {columns[:5]}{'...' if len(columns) > 5 else ''}"
            )
            return False
        
        return True

    @staticmethod
    def _clean_and_sanitize_sheet(df: pl.DataFrame, sheet_name: Optional[str] = None) -> pl.DataFrame:
        if df.is_empty():
            return df
        # Cast all columns to String to prevent mixed-type schema panics on write
        df = df.cast(pl.String)
        
        # Automatic Header Offset / Multi-row Header Cleaner
        unnamed_cols = [c for c in df.columns if '__UNNAMED__' in c.upper() or c.strip() == '' or c.lower().startswith('unnamed')]
        if len(unnamed_cols) >= 2 and len(df) > 1:
            for row_idx in range(min(5, len(df))):
                row_vals = [str(df[c][row_idx] or '').strip() for c in df.columns]
                non_empty = [v for v in row_vals if v and not v.startswith('__UNNAMED__') and not v.lower().startswith('unnamed')]
                if len(non_empty) >= len(df.columns) * 0.4:
                    new_headers = []
                    seen = {}
                    for i, c in enumerate(df.columns):
                        val = str(df[c][row_idx] or '').strip()
                        if not val or val.startswith('__UNNAMED__'):
                            val = c.strip() if not c.startswith('__UNNAMED__') else f"Column_{i+1}"
                        val = val.replace('\n', ' ').strip()
                        if val in seen:
                            seen[val] += 1
                            val = f"{val}_{seen[val]}"
                        else:
                            seen[val] = 1
                        new_headers.append(val)
                    data_df = df.slice(row_idx + 1)
                    data_df.columns = new_headers
                    df = data_df
                    break

        # Sanitize column names: strip trailing dots, newlines, and excess whitespace
        from app.core.excel_extractor import ExcelExtractor
        sanitized_cols = []
        seen_cols = {}
        for i, c in enumerate(df.columns):
            clean_c = ExcelExtractor._normalize_header(str(c)) if hasattr(ExcelExtractor, '_normalize_header') else str(c).replace('\n', ' ').strip().rstrip('.').strip()
            if not clean_c:
                clean_c = f"column_{i+1}"
            if clean_c in seen_cols:
                seen_cols[clean_c] += 1
                clean_c = f"{clean_c}_{seen_cols[clean_c]}"
            else:
                seen_cols[clean_c] = 1
            sanitized_cols.append(clean_c)
        df.columns = sanitized_cols
        
        if sheet_name:
            df = df.with_columns(pl.lit(str(sheet_name)).alias("_sheet_name"))
        return df

    @staticmethod
    def ingest_to_parquet(file_path: str, output_dir: str = "data/parquet", dataset_name: Optional[str] = None) -> tuple[Optional[str], dict, dict]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found.")
            
        # Ensure output dir is relative to the project root, or absolute
        if not os.path.isabs(output_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)
            
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(file_path)
        raw_name = dataset_name or os.path.splitext(base_name)[0]
        name_without_ext = os.path.splitext(raw_name)[0] if raw_name.lower().endswith(('.csv', '.xlsx', '.xls', '.parquet')) else raw_name
        
        # PRODUCTION FIX: Parquet File Lock Contention (Versioning)
        # We append a timestamp so active queries on older files are never violently locked out.
        timestamp = int(time.time())
        versioned_filename = f"{name_without_ext}_{timestamp}.parquet"
        output_path = os.path.join(output_dir, versioned_filename)
        
        logger.info(f"Starting memory-safe versioned ingestion for {file_path} (registry key={name_without_ext})")
        
        try:
            sheet_filenames = []
            registry_sheets = {}
            
            if file_path.lower().endswith('.csv'):
                # Automatically detect separator (comma or tab) by inspecting the first line
                separator = ","
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        first_line = f.readline()
                        if "\t" in first_line and first_line.count("\t") > first_line.count(","):
                            separator = "\t"
                            logger.info(f"Detected tab delimiter for {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to auto-detect delimiter: {e}")
                    
                # PRODUCTION FIX: Schema Evolution (Dirty Data)
                # infer_schema_length=0 forces all columns to String (Utf8).
                # DuckDB will handle strict typing/casting at the semantic SQL layer.
                lf = pl.scan_csv(file_path, separator=separator, ignore_errors=True, infer_schema_length=0)
                
                # Validate that auto-detected headers are real column names, not data values.
                # Polars has no built-in "headerless CSV" detection — if the CSV lacks a header row,
                # the first data row silently becomes column names, corrupting both schema and data.
                detected_columns = lf.collect_schema().names()
                if not ParquetIngester._validate_csv_headers(detected_columns):
                    logger.warning(
                        f"Re-reading CSV with has_header=False due to suspected data-as-headers. "
                        f"Rejected headers: {detected_columns[:5]}{'...' if len(detected_columns) > 5 else ''}"
                    )
                    lf = pl.scan_csv(
                        file_path, separator=separator, ignore_errors=True,
                        infer_schema_length=0, has_header=False
                    )
                    # Polars assigns column_1, column_2, ... when has_header=False
                    logger.info(f"Re-scanned CSV with synthetic headers: {lf.collect_schema().names()[:5]}")
                
                lf.sink_parquet(output_path, row_group_size=100_000)
                sheet_filenames.append(versioned_filename)
                logger.info(f"Successfully streamed CSV to {output_path}")

                
            elif file_path.lower().endswith(('.xlsx', '.xls')):
                # Excel: Discover and process all worksheets via fastexcel / calamine
                import fastexcel
                try:
                    excel_reader = fastexcel.read_excel(file_path)
                    sheet_names = excel_reader.sheet_names
                    logger.info(f"Discovered Excel sheet names in {file_path}: {sheet_names}")
                except Exception as e:
                    logger.warning(f"fastexcel failed reading sheet names ({e}), falling back to default sheet")
                    sheet_names = [None]
                
                sheet_dfs = []
                for sname in sheet_names:
                    try:
                        raw_sheet_df = pl.read_excel(file_path, sheet_name=sname, engine="calamine") if sname is not None else pl.read_excel(file_path, engine="calamine")
                        if raw_sheet_df.is_empty():
                            continue
                        clean_sheet_df = ParquetIngester._clean_and_sanitize_sheet(raw_sheet_df, sheet_name=sname)
                        if clean_sheet_df.is_empty():
                            continue
                        sheet_dfs.append((sname, clean_sheet_df))
                    except Exception as s_err:
                        logger.warning(f"Failed reading sheet {sname!r} from {file_path}: {s_err}")
                
                if not sheet_dfs:
                    raise ValueError(f"No non-empty sheets found in Excel file {file_path}")
                
                # If only 1 sheet exists
                if len(sheet_dfs) == 1:
                    sname, df = sheet_dfs[0]
                    df.write_parquet(output_path, row_group_size=100_000)
                    sheet_filenames.append(versioned_filename)
                else:
                    # Multi-sheet Excel: Write per-sheet parquets AND a unified combined parquet
                    for sname, df in sheet_dfs:
                        clean_sname = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in str(sname)).strip("_") or "sheet"
                        s_filename = f"{name_without_ext}_{clean_sname}_{timestamp}.parquet"
                        s_path = os.path.join(output_dir, s_filename)
                        df.write_parquet(s_path, row_group_size=100_000)
                        sheet_filenames.append(s_filename)
                        registry_sheets[f"{name_without_ext} - {sname}"] = s_filename
                    
                    # Also write the diagonal concatenated combined parquet
                    all_dfs = [df for _, df in sheet_dfs]
                    combined_df = pl.concat(all_dfs, how="diagonal")
                    combined_df.write_parquet(output_path, row_group_size=100_000)
                    logger.info(f"Successfully converted multi-sheet Excel ({len(sheet_dfs)} sheets) to {output_path} and {len(sheet_filenames)} individual sheet parquets.")
                
            else:
                raise ValueError("Unsupported format. Must be CSV or XLSX.")
                
            # Update the registry to point to the newest active dataset and sheets
            registry_path = os.path.join(output_dir, "active_datasets.json")
            registry = {}
            if os.path.exists(registry_path):
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
            
            old_versioned_filename = registry.get(name_without_ext)
            
            registry[name_without_ext] = versioned_filename
            if sheet_filenames:
                registry[f"{name_without_ext}__sheets"] = sheet_filenames
            for k, v in registry_sheets.items():
                registry[k] = v
                
            with open(registry_path, 'w') as f:
                json.dump(registry, f, indent=4)
                
            # Extract schema and categorical registry
            categorical_registry = {}
            schema_registry = {}
            try:
                df = pl.read_parquet(output_path)
                for col in df.columns:
                    schema_registry[col] = str(df[col].dtype)
                    if df[col].dtype == pl.String or df[col].dtype == pl.Utf8:
                        unique_vals = df[col].drop_nulls().unique().to_list()
                        if len(unique_vals) < 50:
                            categorical_registry[col] = unique_vals
            except Exception as e:
                logger.warning(f"Failed to extract schema and categorical values: {e}")
                df = None
                            
            # Build ID index using duckdb to ensure we don't miss numeric IDs
            id_index = {}
            id_index_path = os.path.join(output_dir, f"{name_without_ext}_idindex.json")
            if df is not None:
                try:
                    t0 = time.time()
                    con = duckdb.connect()
                    # We consider any column a potential ID column if it's not a tiny categorical
                    for col in df.columns:
                        if col in categorical_registry:
                            continue
                        
                        # Read unique values cast to string, upper-cased and trimmed
                        query = f"""
                            SELECT DISTINCT UPPER(TRIM(CAST("{col}" AS VARCHAR))) 
                            FROM read_parquet(?)
                            WHERE "{col}" IS NOT NULL
                        """
                        values = con.execute(query, [output_path]).fetchall()
                        
                        # Filter out purely short noise, keep if reasonable cardinality
                        vals = [v[0] for v in values if v[0] and len(v[0]) > 2]
                        if 0 < len(vals) < 100000:
                            id_index[col] = vals
                    
                    with open(id_index_path, 'w') as f:
                        json.dump(id_index, f)
                    
                    logger.info(f"Built ID index for {name_without_ext} in {time.time()-t0:.2f}s: {len(id_index)} columns, {sum(len(v) for v in id_index.values())} total values")
                except Exception as e:
                    logger.warning(f"Failed to build ID index: {e}")
                
            # POST-SUCCESS CLEANUP: Safely remove obsolete previous versions after reference update
            ParquetIngester._cleanup_obsolete_versions(
                dataset_name=name_without_ext,
                active_filename=versioned_filename,
                output_dir=output_dir,
                old_versioned_filename=old_versioned_filename
            )

            return output_path, categorical_registry, schema_registry
            
        except Exception as e:
            logger.error(f"Failed to ingest file to Parquet: {e}")
            raise e
            
    @staticmethod
    def _clean_dataset_name(name: str) -> str:
        if not name:
            return ""
        n = str(name).strip()
        for prefix in ["Spreadsheet: ", "spreadsheet: ", "Document: ", "document: ", "PDF: ", "pdf: "]:
            if n.startswith(prefix):
                n = n[len(prefix):].strip()
        for ext in [".xlsx", ".xls", ".csv", ".parquet"]:
            if n.lower().endswith(ext):
                n = n[:-len(ext)].strip()
        return n

    @staticmethod
    def _cleanup_obsolete_versions(dataset_name: str, active_filename: str, output_dir: str, old_versioned_filename: Optional[str] = None):
        """
        Safely removes obsolete, unreferenced versioned Parquet files for a given dataset
        only AFTER new file creation and registry update have succeeded.
        """
        try:
            # 1. Clean explicit previous file recorded in registry if present
            if old_versioned_filename and old_versioned_filename != active_filename:
                old_file_path = os.path.join(output_dir, old_versioned_filename)
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                        logger.info(f"Post-success cleanup: Removed previous Parquet version {old_file_path}")
                    except Exception as err:
                        logger.warning(f"Post-success cleanup: Could not delete prior version {old_file_path} (may be locked): {err}")

            # 2. Sweep for any untracked orphan files matching {dataset_name}_*.parquet that are not active_filename
            if os.path.exists(output_dir):
                prefix = f"{dataset_name}_"
                for fname in os.listdir(output_dir):
                    if fname.startswith(prefix) and fname.endswith(".parquet") and fname != active_filename:
                        orphan_path = os.path.join(output_dir, fname)
                        try:
                            os.remove(orphan_path)
                            logger.info(f"Post-success cleanup: Removed orphan Parquet version {orphan_path}")
                        except Exception as err:
                            logger.warning(f"Post-success cleanup: Could not remove orphan file {orphan_path}: {err}")
        except Exception as e:
            logger.error(f"Error during post-success Parquet cleanup for {dataset_name}: {e}")

    @staticmethod
    def get_active_dataset(dataset_name: str, output_dir: str = "data/parquet") -> Optional[str]:
        """
        Retrieves the filepath of the most recent version of a dataset.
        Includes single-source-of-truth registry lookup + resilient fuzzy fallback sweep.
        """
        if not dataset_name:
            return None

        if not os.path.isabs(output_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)

        clean_name = ParquetIngester._clean_dataset_name(dataset_name)
        clean_key = clean_name
        if clean_key.lower().endswith(('.csv', '.xlsx', '.xls', '.parquet')):
            clean_key = os.path.splitext(clean_key)[0]

        # 1. Primary Registry Lookup
        registry_path = os.path.join(output_dir, "active_datasets.json")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
                    lookup_keys = [clean_key, clean_name, dataset_name, dataset_name.strip()]
                    for key in lookup_keys:
                        if key in registry:
                            candidate = os.path.join(output_dir, registry[key])
                            if os.path.exists(candidate):
                                return candidate
                            logger.warning(f"[PARQUET_REGISTRY] Key '{key}' in registry points to missing file '{candidate}'. Running fallback sweep...")
                    
                    # Case-insensitive / normalized search in registry
                    norm_target = clean_name.lower().replace(" ", "").replace("_", "").replace("-", "")
                    for k, v in registry.items():
                        if k.endswith("__sheets"):
                            continue
                        k_norm = k.lower().replace(" ", "").replace("_", "").replace("-", "")
                        if k_norm == norm_target:
                            candidate = os.path.join(output_dir, v)
                            if os.path.exists(candidate):
                                return candidate
            except Exception as reg_err:
                logger.warning(f"[PARQUET_REGISTRY] Failed to read registry at {registry_path}: {reg_err}")

        # 2. Resilient Fuzzy / Glob Fallback Sweep
        if os.path.exists(output_dir):
            target_prefix = f"{clean_key.lower()}_"
            target_exact = f"{clean_key.lower()}.parquet"

            candidates = []
            for fname in os.listdir(output_dir):
                fn_lower = fname.lower()
                if fn_lower == target_exact or (fn_lower.startswith(target_prefix) and fn_lower.endswith(".parquet")):
                    full_p = os.path.join(output_dir, fname)
                    if os.path.exists(full_p):
                        mtime = os.path.getmtime(full_p)
                        candidates.append((mtime, full_p))

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                selected_path = candidates[0][1]
                logger.warning(f"[PARQUET_REGISTRY_FALLBACK] Resolved dataset '{dataset_name}' to newest parquet file '{selected_path}' via fuzzy fallback sweep.")
                return selected_path

        logger.error(f"[PARQUET_REGISTRY] Could not find any parquet file for dataset_name='{dataset_name}' in '{output_dir}'")
        return None

    @staticmethod
    def get_active_datasets(dataset_name: str, output_dir: str = "data/parquet") -> List[str]:
        """Retrieves all active sheet parquet filepaths for a dataset (or the single parquet if single-sheet)."""
        if not os.path.isabs(output_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)
            
        clean_name = ParquetIngester._clean_dataset_name(dataset_name)
        registry_path = os.path.join(output_dir, "active_datasets.json")
        if os.path.exists(registry_path):
            with open(registry_path, 'r') as f:
                registry = json.load(f)
                
                # Check explicit sheets key (exact, clean, or normalized)
                for key_to_try in [f"{dataset_name}__sheets", f"{clean_name}__sheets"]:
                    if key_to_try in registry and isinstance(registry[key_to_try], list):
                        paths = [os.path.join(output_dir, fn) for fn in registry[key_to_try]]
                        valid_paths = [p for p in paths if os.path.exists(p)]
                        if valid_paths:
                            return valid_paths
                            
                norm_target = clean_name.lower().replace(" ", "").replace("_", "").replace("-", "")
                for k, v in registry.items():
                    if k.endswith("__sheets") and isinstance(v, list):
                        k_norm = k[:-8].lower().replace(" ", "").replace("_", "").replace("-", "")
                        if k_norm == norm_target:
                            paths = [os.path.join(output_dir, fn) for fn in v]
                            valid_paths = [p for p in paths if os.path.exists(p)]
                            if valid_paths:
                                return valid_paths

        # Fallback to single active dataset
        single = ParquetIngester.get_active_dataset(dataset_name, output_dir=output_dir)
        if single and os.path.exists(single):
            return [single]
            
        # Fallback to physical scan of sheet parquets
        import glob
        pattern = os.path.join(output_dir, f"{clean_name}_*.parquet")
        matches = glob.glob(pattern)
        if matches:
            return matches

        return []

    @staticmethod
    def delete_active_dataset(dataset_name: str, output_dir: str = "data/parquet") -> bool:
        """Deletes all physical Parquet file(s) and registry entry for a dataset."""
        if not os.path.isabs(output_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)
            
        registry_path = os.path.join(output_dir, "active_datasets.json")
        deleted_any = False
        try:
            registry = {}
            if os.path.exists(registry_path):
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
                
                if dataset_name in registry:
                    filename = registry[dataset_name]
                    file_path = os.path.join(output_dir, filename)
                    
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            logger.info(f"Deleted physical Parquet file: {file_path}")
                            deleted_any = True
                        except Exception as err:
                            logger.warning(f"Physical Parquet file not found or locked: {file_path}: {err}")
                    
                    del registry[dataset_name]
                    with open(registry_path, 'w') as f:
                        json.dump(registry, f, indent=4)
                    logger.info(f"Removed registry entry for {dataset_name}")

            # Also sweep and remove any orphaned versioned files matching {dataset_name}_*.parquet
            if os.path.exists(output_dir):
                prefix = f"{dataset_name}_"
                for fname in os.listdir(output_dir):
                    if fname.startswith(prefix) and fname.endswith(".parquet"):
                        orphan_path = os.path.join(output_dir, fname)
                        try:
                            os.remove(orphan_path)
                            logger.info(f"Deleted orphaned versioned Parquet file: {orphan_path}")
                            deleted_any = True
                        except Exception as err:
                            logger.warning(f"Could not delete orphan Parquet file {orphan_path}: {err}")
                            
            return deleted_any
        except Exception as e:
            logger.error(f"Failed to delete active dataset {dataset_name}: {e}")
            return False
