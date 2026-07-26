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
    def ingest_to_parquet(file_path: str, output_dir: str = "data/parquet", dataset_name: Optional[str] = None) -> Optional[str]:
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
                # PRODUCTION FIX: Schema Evolution (Dirty Data)
                # infer_schema_length=0 forces all columns to String (Utf8).
                # DuckDB will handle strict typing/casting at the semantic SQL layer.
                lf = pl.scan_csv(file_path, ignore_errors=True, infer_schema_length=0)
                lf.sink_parquet(output_path, row_group_size=100_000)
                logger.info(f"Successfully streamed CSV to {output_path}")
                
            elif file_path.lower().endswith(('.xlsx', '.xls')):
                # Excel: Use the fastexcel (calamine) engine which avoids loading XML trees into RAM
                df = pl.read_excel(file_path, engine="calamine")
                # Cast all columns to String to prevent mixed-type schema panics on write
                df = df.cast(pl.String)
                df.write_parquet(output_path, row_group_size=100_000)
                logger.info(f"Successfully converted Excel to {output_path}")
                
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
                
            return output_path
            
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
