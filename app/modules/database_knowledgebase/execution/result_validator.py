"""Phase 2C Result Validation and Type Normalization

Validates returned database records against authorized schema structure,
enforces column and cell bounds, and normalizes database driver types into
lossless, JSON-serializable canonical representations (Decimal -> string, datetime -> ISO-8601).
"""

from datetime import date, datetime, time
from decimal import Decimal
import json
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
import asyncpg

from .errors import ResultLimitExceeded, ResultValidationError
from .models import ExecutionConfig


class ResultValidator:
    """Validates and normalizes database result sets."""

    @classmethod
    def normalize_value(cls, val: Any, max_cell_length: int) -> Any:
        """
        Losslessly convert database driver types to serializable primitives.
        CRITICAL: Preserves numeric precision of Decimal by converting to exact string.
        """
        if val is None:
            return None

        # 1. Decimal -> Exact String Representation (No floating-point rounding)
        if isinstance(val, Decimal):
            return str(val)

        # 2. Temporal Types -> ISO 8601 Strings
        if isinstance(val, (datetime, date, time)):
            return val.isoformat()

        # 3. UUID -> String
        if isinstance(val, uuid.UUID):
            return str(val)

        # 4. Bytes / Bytearray -> Hex string
        if isinstance(val, (bytes, bytearray)):
            return val.hex()

        # 5. String length bounding
        if isinstance(val, str):
            if len(val) > max_cell_length:
                return val[:max_cell_length] + " [TRUNCATED]"
            return val

        # 6. Dict / List (JSON or JSONB types) -> recursively normalize
        if isinstance(val, dict):
            return {str(k): cls.normalize_value(v, max_cell_length) for k, v in val.items()}
        if isinstance(val, list):
            return [cls.normalize_value(item, max_cell_length) for item in val]

        # 7. Basic primitives (int, float, bool)
        return val

    @classmethod
    def infer_type_name(cls, val: Any) -> str:
        """Infer canonical relational data type name from sample value."""
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "BOOLEAN"
        if isinstance(val, int):
            return "INTEGER"
        if isinstance(val, (Decimal, float)):
            return "DECIMAL"
        if isinstance(val, datetime):
            return "TIMESTAMPTZ"
        if isinstance(val, date):
            return "DATE"
        if isinstance(val, time):
            return "TIME"
        if isinstance(val, uuid.UUID):
            return "UUID"
        if isinstance(val, (dict, list)):
            return "JSON"
        return "VARCHAR"

    @classmethod
    def validate_and_normalize(
        cls,
        records: List[asyncpg.Record],
        config: ExecutionConfig,
        authorized_columns: Optional[List[str]] = None,
    ) -> Tuple[List[str], Dict[str, str], List[Dict[str, Any]], List[str]]:
        """
        Validates column counts and types, extracts column names, and normalizes rows.
        Returns: (columns, column_types, normalized_rows, warnings)
        """
        warnings: List[str] = []

        if not records:
            return [], {}, [], warnings

        # 1. Inspect Columns from first record
        first_row = records[0]
        columns = list(first_row.keys())

        # Check column count bounds
        if len(columns) > config.max_columns:
            raise ResultLimitExceeded(
                detail=f"Query returned {len(columns)} columns, exceeding maximum allowed of {config.max_columns}.",
                details={"column_count": len(columns), "max_columns": config.max_columns},
            )

        # 2. Determine column types from records
        column_types: Dict[str, str] = {}
        for col in columns:
            col_type = "UNKNOWN"
            for r in records:
                val = r[col]
                if val is not None:
                    col_type = cls.infer_type_name(val)
                    break
            column_types[col] = col_type

        # 3. Normalize all rows
        normalized_rows: List[Dict[str, Any]] = []
        for r in records:
            row_dict: Dict[str, Any] = {}
            for col in columns:
                val = r[col]
                row_dict[col] = cls.normalize_value(val, config.max_cell_length)
            normalized_rows.append(row_dict)

        return columns, column_types, normalized_rows, warnings
