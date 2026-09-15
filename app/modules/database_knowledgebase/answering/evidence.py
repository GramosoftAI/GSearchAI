"""Evidence Extractor for Phase 2D Answer Synthesis

Extracts structured, lossless evidence from CanonicalQueryResult, tracking
exact numerical representations, valid derivations, named entities, and column metrics.
"""

from decimal import Decimal
import re
from typing import Any, Dict, List, Optional, Set
import uuid

from ..execution.models import CanonicalQueryResult
from .calculator import DecimalCalculator
from .models import EvidenceModel

SPELLED_NUMBERS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
}


class EvidenceExtractor:
    """Extracts structured evidence and supported fact sets from CanonicalQueryResult."""

    @classmethod
    def extract(cls, result: CanonicalQueryResult, user_query: str = "") -> EvidenceModel:
        """
        Transform CanonicalQueryResult into a structured EvidenceModel.
        Guarantees exact Decimal preservation and computes allowed deterministic derivations.
        """
        supported_numbers: Set[str] = set()
        supported_entities: Set[str] = set()
        summary_metrics: Dict[str, str] = {}

        rows = result.rows or []
        columns = result.columns or []
        row_count = result.row_count

        # 1. Register column names and their title-cased labels as supported entities
        for col in columns:
            supported_entities.add(col)
            supported_entities.add(col.replace("_", " ").title())
            for part in col.split("_"):
                if len(part) >= 2:
                    supported_entities.add(part.title())

        # 2. Register row_count as supported number
        cls._add_number_variants(str(row_count), supported_numbers)
        summary_metrics["row_count"] = str(row_count)

        # 2. Extract numbers from user query itself (e.g. "order #500", "$100", "2026")
        if user_query:
            query_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", user_query)
            for qn in query_numbers:
                cls._add_number_variants(qn, supported_numbers)

        # 3. Allow rank numbers from 1 to row_count (e.g. 1st, 2nd, 3, 4, 5)
        for rank in range(1, min(row_count + 1, 100)):
            cls._add_number_variants(str(rank), supported_numbers)

        # 4. Extract cell values, numbers, entities, and timestamps from rows
        numeric_columns: Dict[str, List[Any]] = {col: [] for col in columns}

        for row in rows:
            for col, val in row.items():
                if val is None:
                    continue

                str_val = str(val).strip()

                # Check if value is numeric or currency
                dec = DecimalCalculator.to_decimal(val)
                if dec is not None:
                    cls._add_number_variants(str_val, supported_numbers)
                    numeric_columns.setdefault(col, []).append(val)
                else:
                    # Treat text values as supported entities/data
                    if len(str_val) > 0 and len(str_val) < 200:
                        supported_entities.add(str_val)
                        # Add individual word tokens for entity matching (split on any non-alphanumeric, including hyphens, slashes, punctuation)
                        for token in re.findall(r"[A-Za-z0-9]+", str_val):
                            if len(token) >= 2:
                                supported_entities.add(token)
                                supported_entities.add(token.title())
                        # Extract any numbers embedded in text cells (e.g. street numbers "500", postal codes, building numbers)
                        for num_token in re.findall(r"\b\d+(?:\.\d+)?\b", str_val):
                            cls._add_number_variants(num_token, supported_numbers)

                    # Extract year / month from ISO timestamps (e.g. "2026-02-01T...")
                    if re.match(r"^\d{4}-\d{2}-\d{2}", str_val):
                        year = str_val[:4]
                        cls._add_number_variants(year, supported_numbers)

        # 5. Precalculate deterministic aggregations for numeric columns
        for col, vals in numeric_columns.items():
            if vals:
                col_sum = DecimalCalculator.calculate_sum(vals)
                if col_sum is not None:
                    cls._add_number_variants(col_sum, supported_numbers)
                    summary_metrics[f"{col}_sum"] = col_sum

                col_avg = DecimalCalculator.calculate_average(vals, decimal_places=2)
                if col_avg is not None:
                    cls._add_number_variants(col_avg, supported_numbers)
                    summary_metrics[f"{col}_avg"] = col_avg

                col_min = DecimalCalculator.calculate_min(vals)
                if col_min is not None:
                    cls._add_number_variants(col_min, supported_numbers)
                    summary_metrics[f"{col}_min"] = col_min

                col_max = DecimalCalculator.calculate_max(vals)
                if col_max is not None:
                    cls._add_number_variants(col_max, supported_numbers)
                    summary_metrics[f"{col}_max"] = col_max

        # 6. Extract entity keywords from user query
        if user_query:
            for token in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", user_query):
                supported_entities.add(token)

        return EvidenceModel(
            query_id=result.query_id,
            database_knowledgebase_id=result.database_knowledgebase_id,
            schema_version=result.schema_version,
            columns=columns,
            column_types=result.column_types or {},
            rows=rows,
            row_count=row_count,
            truncated=result.truncated,
            execution_time_ms=result.execution_time_ms,
            supported_numbers=sorted(list(supported_numbers)),
            supported_entities=sorted(list(supported_entities)),
            summary_metrics=summary_metrics,
        )

    @classmethod
    def _add_number_variants(cls, num_str: str, target_set: Set[str]) -> None:
        """Add exact raw number and all standard formatting variants to the supported set."""
        clean = num_str.strip().replace("$", "").replace(",", "")
        try:
            dec = Decimal(clean)
        except Exception:
            target_set.add(num_str)
            return

        # 1. Exact canonical string
        target_set.add(str(dec))
        target_set.add(clean)

        # 2. Integer variant if whole number
        if dec == dec.to_integral_value():
            int_str = str(int(dec))
            target_set.add(int_str)
            # Spelled-out version for small integers (e.g. 5 -> "five")
            if int_str in SPELLED_NUMBERS:
                target_set.add(SPELLED_NUMBERS[int_str])

        # 3. Formatted currency ($1,692.98 and $1692.98)
        formatted_curr = DecimalCalculator.format_currency(dec)
        target_set.add(formatted_curr)
        target_set.add(formatted_curr.replace("$", ""))  # 1,692.98
        target_set.add(f"${clean}")                     # $1692.98

        # 4. Standard 2-decimal place representation
        two_dec = f"{dec:.2f}"
        target_set.add(two_dec)
