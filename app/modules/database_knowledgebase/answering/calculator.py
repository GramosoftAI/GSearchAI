"""Deterministic Decimal Calculator for Phase 2D Answer Synthesis

Provides exact, deterministic mathematical operations using Python's Decimal type.
Strictly avoids IEEE-754 floating-point coercion to guarantee that monetary and
statistical values preserve database precision without rounding errors.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, List, Optional, Tuple, Union


class DecimalCalculator:
    """Performs deterministic arithmetic calculations over database values."""

    @staticmethod
    def to_decimal(val: Any) -> Optional[Decimal]:
        """Safely convert any numeric or string representation to Decimal."""
        if val is None:
            return None
        if isinstance(val, Decimal):
            return val
        clean_str = str(val).strip().replace("$", "").replace(",", "")
        try:
            return Decimal(clean_str)
        except (InvalidOperation, ValueError):
            return None

    @classmethod
    def calculate_sum(cls, values: List[Any]) -> Optional[str]:
        """Calculate exact sum of numeric values, returning exact string representation."""
        decimals = [cls.to_decimal(v) for v in values if v is not None]
        valid_decimals = [d for d in decimals if d is not None]
        if not valid_decimals:
            return None
        total = sum(valid_decimals[1:], valid_decimals[0])
        return str(total)

    @classmethod
    def calculate_count(cls, values: List[Any]) -> int:
        """Count non-null items."""
        return sum(1 for v in values if v is not None)

    @classmethod
    def calculate_average(cls, values: List[Any], decimal_places: int = 2) -> Optional[str]:
        """Calculate average rounded to specified decimal places using ROUND_HALF_UP."""
        decimals = [cls.to_decimal(v) for v in values if v is not None]
        valid_decimals = [d for d in decimals if d is not None]
        if not valid_decimals:
            return None
        total = sum(valid_decimals[1:], valid_decimals[0])
        avg = total / Decimal(len(valid_decimals))
        quantize_str = "0." + "0" * decimal_places if decimal_places > 0 else "0"
        return str(avg.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP))

    @classmethod
    def calculate_min(cls, values: List[Any]) -> Optional[str]:
        """Find minimum value in a numeric list preserving exact string representation."""
        decimals = [(cls.to_decimal(v), str(v)) for v in values if v is not None]
        valid = [(d, s) for d, s in decimals if d is not None]
        if not valid:
            return None
        min_item = min(valid, key=lambda x: x[0])
        return str(min_item[0])

    @classmethod
    def calculate_max(cls, values: List[Any]) -> Optional[str]:
        """Find maximum value in a numeric list preserving exact string representation."""
        decimals = [(cls.to_decimal(v), str(v)) for v in values if v is not None]
        valid = [(d, s) for d, s in decimals if d is not None]
        if not valid:
            return None
        max_item = max(valid, key=lambda x: x[0])
        return str(max_item[0])

    @classmethod
    def calculate_percentage(
        cls,
        part: Any,
        total: Any,
        decimal_places: int = 1,
    ) -> Optional[str]:
        """Calculate percentage (part / total * 100)."""
        dec_part = cls.to_decimal(part)
        dec_total = cls.to_decimal(total)
        if dec_part is None or dec_total is None or dec_total == Decimal(0):
            return None
        pct = (dec_part / dec_total) * Decimal(100)
        quantize_str = "0." + "0" * decimal_places if decimal_places > 0 else "0"
        return str(pct.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)) + "%"

    @classmethod
    def format_currency(cls, val: Any) -> str:
        """
        Format value as standard USD currency string ($1,234.56).
        Preserves exact decimal precision without floating point conversion.
        """
        dec = cls.to_decimal(val)
        if dec is None:
            return str(val)
        # Separate whole and fractional parts
        sign = "-" if dec < 0 else ""
        abs_dec = abs(dec)
        str_val = f"{abs_dec:.2f}"
        if "." in str_val:
            whole, frac = str_val.split(".", 1)
        else:
            whole, frac = str_val, "00"
        # Add thousands separators to whole part
        reversed_whole = whole[::-1]
        chunks = [reversed_whole[i:i+3] for i in range(0, len(reversed_whole), 3)]
        formatted_whole = ",".join(chunks)[::-1]
        return f"{sign}${formatted_whole}.{frac}"
