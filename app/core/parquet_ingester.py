import polars as pl
import os
import logging
import time
import json
from typing import Optional

logger = logging.getLogger(__name__)

class ParquetIngester:
    """
    Enterprise-grade ingestion layer for 1M+ row datasets.
    Safely streams large CSVs or reads massive Excel files using memory-efficient Calamine,
    and writes them out as chunked, compressed Parquet files for DuckDB querying.
    """
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
        name_without_ext = dataset_name or os.path.splitext(base_name)[0]
        
        # PRODUCTION FIX: Parquet File Lock Contention (Versioning)
        # We append a timestamp so active queries on older files are never violently locked out.
        timestamp = int(time.time())
        versioned_filename = f"{name_without_ext}_{timestamp}.parquet"
        output_path = os.path.join(output_dir, versioned_filename)
        
        logger.info(f"Starting memory-safe versioned ingestion for {file_path}")
        
        try:
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
                lf.sink_parquet(output_path, row_group_size=100_000)
                logger.info(f"Successfully streamed CSV to {output_path}")
                
            elif file_path.lower().endswith(('.xlsx', '.xls')):
                from app.core.excel_extractor import ExcelExtractor
                import fastexcel

                # Excel: Use fastexcel to discover all sheet names
                excel_reader = fastexcel.read_excel(file_path)
                sheet_names = excel_reader.sheet_names
                logger.info(f"Discovered Excel sheet names in {file_path}: {sheet_names}")

                best_df = None
                max_rows = -1
                best_sheet = sheet_names[0] if sheet_names else None

                for sname in sheet_names:
                    try:
                        temp_df = pl.read_excel(file_path, sheet_name=sname, engine="calamine", has_header=False)
                        if temp_df.height > max_rows:
                            max_rows = temp_df.height
                            best_df = temp_df
                            best_sheet = sname
                    except Exception as se:
                        logger.warning(f"Failed to read sheet '{sname}' in {file_path}: {se}")

                if best_df is None or max_rows <= 0:
                    best_df = pl.read_excel(file_path, engine="calamine", has_header=False)
                    best_sheet = "default"

                logger.info(f"Selected primary data sheet '{best_sheet}' with {max_rows} rows for Parquet ingestion.")
                df = best_df

                # Run the robust pandas header heuristic on the first 30 rows
                df_head = df.head(30).to_pandas()
                header_idx = ExcelExtractor._detect_header_row(df_head)

                # Extract headers and slice the polars dataframe
                raw_headers = df.row(header_idx)
                df = df.slice(header_idx + 1)

                # Normalize headers and apply to columns
                norm_cols = []
                seen = set()
                for i, h in enumerate(raw_headers):
                    norm = ExcelExtractor._normalize_header(str(h)) or f"unnamed_{i}"
                    while norm in seen:
                        norm = f"{norm}_{i}"
                    seen.add(norm)
                    norm_cols.append(norm)

                df.columns = norm_cols
                # Cast all columns to String to prevent mixed-type schema panics on write
                df = df.cast(pl.String)
                df.write_parquet(output_path, row_group_size=100_000)
                logger.info(f"Successfully converted Excel sheet '{best_sheet}' to {output_path} (header row {header_idx}, total rows {df.height})")
                
            else:
                raise ValueError("Unsupported format. Must be CSV or XLSX.")
                
            # Update the registry to point to the newest active dataset
            registry_path = os.path.join(output_dir, "active_datasets.json")
            registry = {}
            if os.path.exists(registry_path):
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
            
            old_versioned_filename = registry.get(name_without_ext)
            
            registry[name_without_ext] = versioned_filename
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
        """Retrieves the filepath of the most recent version of a dataset."""
        if not os.path.isabs(output_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)
            
        registry_path = os.path.join(output_dir, "active_datasets.json")
        if os.path.exists(registry_path):
            with open(registry_path, 'r') as f:
                registry = json.load(f)
                if dataset_name in registry:
                    return os.path.join(output_dir, registry[dataset_name])
        return None

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
