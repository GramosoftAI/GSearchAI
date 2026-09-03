import polars as pl
import os
import logging
import time
import json
import duckdb
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
                # Excel: Use the fastexcel (calamine) engine which avoids loading XML trees into RAM
                # Read without assuming header to prevent title rows from becoming the schema
                df = pl.read_excel(file_path, engine="calamine", has_header=False)
                
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
                logger.info(f"Successfully converted Excel to {output_path} (header row {header_idx})")
                
            else:
                raise ValueError("Unsupported format. Must be CSV or XLSX.")
                
            # Update the registry to point to the newest active dataset
            registry_path = os.path.join(output_dir, "active_datasets.json")
            registry = {}
            if os.path.exists(registry_path):
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
            
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
                
            return output_path, categorical_registry, schema_registry
            
        except Exception as e:
            logger.error(f"Failed to ingest file to Parquet: {e}")
            raise e
            
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
        """Deletes the physical Parquet file and its registry entry from active_datasets.json."""
        if not os.path.isabs(output_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(base_dir, output_dir)
            
        registry_path = os.path.join(output_dir, "active_datasets.json")
        if not os.path.exists(registry_path):
            return False
            
        try:
            with open(registry_path, 'r') as f:
                registry = json.load(f)
                
            if dataset_name in registry:
                filename = registry[dataset_name]
                file_path = os.path.join(output_dir, filename)
                
                # Delete physical file
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted physical Parquet file: {file_path}")
                else:
                    logger.warning(f"Physical Parquet file not found to delete: {file_path}")
                
                # Remove from registry
                del registry[dataset_name]
                with open(registry_path, 'w') as f:
                    json.dump(registry, f, indent=4)
                logger.info(f"Removed registry entry for {dataset_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to delete active dataset {dataset_name}: {e}")
        return False
