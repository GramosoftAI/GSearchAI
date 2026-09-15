"""Deterministic Schema Fingerprinting & Versioning

Computes a deterministic cryptographic SHA-256 hash of the canonical schema representation.
Guarantees:
- Identical schema structure produces identical fingerprint regardless of object ordering.
- Adding, removing, or modifying tables, columns, types, nullability, primary keys, or foreign keys
  strictly changes the fingerprint (drift detection).
"""

import hashlib
import json
from typing import Dict, Any
from ..schemas.canonical import DatabaseSchema


class SchemaFingerprinter:
    """Computes deterministic fingerprints from canonical DatabaseSchema objects."""

    @classmethod
    def generate_fingerprint(cls, schema: DatabaseSchema) -> str:
        """
        Produce a deterministic SHA-256 hexadecimal hash representing the technical schema structure.
        """
        canonical_dict = cls._to_deterministic_dict(schema)
        json_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    @classmethod
    def _to_deterministic_dict(cls, schema: DatabaseSchema) -> Dict[str, Any]:
        """
        Extract structural technical elements into sorted, deterministic dictionary.
        """
        schemas_data = {}
        for s_name in sorted(schema.schemas.keys()):
            s_info = schema.schemas[s_name]
            tables_data = {}

            for t_name in sorted(s_info.tables.keys()):
                table = s_info.tables[t_name]

                # 1. Sorted Columns Structure
                cols_data = []
                for c_name in sorted(table.columns.keys()):
                    col = table.columns[c_name]
                    cols_data.append({
                        "name": col.name,
                        "data_type": col.data_type.value,
                        "is_nullable": col.is_nullable,
                        "is_primary_key": col.is_primary_key,
                        "is_foreign_key": col.is_foreign_key,
                    })

                # 2. Primary Key
                pk_data = []
                if table.primary_key:
                    pk_data = sorted(table.primary_key.constrained_columns)

                # 3. Foreign Keys
                fks_data = []
                for fk in sorted(table.foreign_keys, key=lambda f: (f.referred_table, ",".join(f.constrained_columns))):
                    fks_data.append({
                        "source_columns": sorted(fk.constrained_columns),
                        "referred_schema": fk.referred_schema,
                        "referred_table": fk.referred_table,
                        "referred_columns": sorted(fk.referred_columns),
                    })

                tables_data[t_name] = {
                    "table_type": table.table_type,
                    "columns": cols_data,
                    "primary_key": pk_data,
                    "foreign_keys": fks_data,
                }

            schemas_data[s_name] = tables_data

        return {
            "database_name": schema.database_name,
            "database_type": schema.database_type,
            "schemas": schemas_data,
        }
