"""Deterministic Formatters for Phase 2D Answer Synthesis

Produces zero-hallucination, 100% mathematically exact formatted answers
for scalars, counts, sums, empty results, rankings, and structured tables.
Bypasses LLM entirely for high-confidence deterministic paths.
"""

from typing import Any, Dict, List, Optional
from .calculator import DecimalCalculator
from .models import AnswerType, EvidenceModel


class DeterministicFormatter:
    """Provides deterministic formatting methods for database evidence."""

    @staticmethod
    def format_empty(user_query: str, evidence: EvidenceModel) -> str:
        """Format a clear, factual answer when row_count == 0."""
        return "No matching records were found in the database for this query."

    @staticmethod
    def format_scalar(user_query: str, evidence: EvidenceModel) -> str:
        """Format a single scalar or aggregate metric with exact precision."""
        if not evidence.rows or not evidence.columns:
            return "No data available."
        
        row = evidence.rows[0]
        col = evidence.columns[0]
        val = row.get(col)

        # Check if query or column is a count vs monetary/numerical
        dec = DecimalCalculator.to_decimal(val)
        q_lower = user_query.lower()
        c_lower = col.lower()
        is_count = any(k in q_lower for k in ["how many", "count"]) or "count" in c_lower

        is_currency = (not is_count) and any(k in c_lower or k in q_lower for k in [
            "sales", "amount", "price", "revenue", "spending",
            "salary", "pay", "budget", "cost", "wage", "compensation"
        ])

        if dec is not None:
            if is_currency:
                val_str = DecimalCalculator.format_currency(dec)
            elif is_count or (dec % 1 == 0):
                val_str = str(int(dec))
            else:
                val_str = f"{dec:.2f}"
        else:
            val_str = str(val)

        # Natural presentation based on query keywords or column name
        q_lower = user_query.lower()
        c_lower = col.lower()

        if any(k in q_lower for k in ["how many", "count"]) or "count" in c_lower:
            return f"The total count is {val_str}."
        elif any(k in q_lower for k in ["total sales", "total revenue"]):
            return f"The total sales across all orders is {val_str}."
        elif any(k in q_lower for k in ["highest", "max", "maximum"]) or any(k in c_lower for k in ["max", "highest"]):
            return f"The highest value recorded is {val_str}."
        elif any(k in q_lower for k in ["lowest", "min", "minimum"]) or any(k in c_lower for k in ["min", "lowest"]):
            return f"The lowest value recorded is {val_str}."
        elif any(k in q_lower for k in ["average", "avg"]) or any(k in c_lower for k in ["avg", "average"]):
            return f"The average value is {val_str}."
        elif any(k in q_lower for k in ["total", "sum"]) or any(k in c_lower for k in ["sum", "total"]):
            return f"The total is {val_str}."

        clean_col = col.replace("_", " ").title()
        return f"{clean_col}: {val_str}"

    @staticmethod
    def format_ranking(user_query: str, evidence: EvidenceModel, label_col: str, value_col: str) -> str:
        """Format ordered ranking list with exact values."""
        rows = evidence.rows
        lines = []
        q_lower = user_query.lower()
        
        title = "Top results:"
        if "customer" in q_lower:
            title = "Top customers by total spending:"
        elif "product" in q_lower:
            title = "Top products:"

        lines.append(title)
        is_currency = any(k in value_col.lower() for k in ["amount", "price", "spending", "total", "revenue"])

        for i, row in enumerate(rows, 1):
            label = row.get(label_col, f"Item {i}")
            val = row.get(value_col, "")
            if is_currency:
                dec = DecimalCalculator.to_decimal(val)
                if dec is not None:
                    val = DecimalCalculator.format_currency(dec)
            lines.append(f"{i}. {label}: {val}")

        return "\n".join(lines)

    @staticmethod
    def format_single_row(user_query: str, evidence: EvidenceModel) -> str:
        """Format single record as key-value list."""
        if not evidence.rows:
            return "No matching record found."
        row = evidence.rows[0]
        lines = ["Matching record details:"]
        for col, val in row.items():
            clean_col = col.replace("_", " ").title()
            dec = DecimalCalculator.to_decimal(val)
            if dec is not None and any(k in col.lower() for k in ["amount", "price", "total", "revenue"]):
                formatted_val = DecimalCalculator.format_currency(dec)
            else:
                formatted_val = str(val) if val is not None else "N/A"
            lines.append(f"- **{clean_col}**: {formatted_val}")
        return "\n".join(lines)

    @staticmethod
    def format_table(user_query: str, evidence: EvidenceModel, max_display_rows: int = 25) -> str:
        """Format rows as a standard Markdown table."""
        if not evidence.rows or not evidence.columns:
            return "No matching records found."

        cols = evidence.columns
        display_rows = evidence.rows[:max_display_rows]

        # Build table header
        header_line = "| " + " | ".join(c.replace("_", " ").title() for c in cols) + " |"
        sep_line = "| " + " | ".join("---" for _ in cols) + " |"
        row_lines = []

        for row in display_rows:
            vals = []
            for c in cols:
                v = row.get(c)
                dec = DecimalCalculator.to_decimal(v)
                if dec is not None and any(k in c.lower() for k in ["amount", "price", "total", "revenue"]):
                    vals.append(DecimalCalculator.format_currency(dec))
                else:
                    vals.append(str(v) if v is not None else "-")
            row_lines.append("| " + " | ".join(vals) + " |")

        table_str = "\n".join([header_line, sep_line] + row_lines)
        if evidence.row_count > max_display_rows:
            table_str += f"\n\n*Showing first {max_display_rows} of {evidence.row_count} records.*"

        # Append exact deterministic summaries for totals
        sum_notes = []
        for k, v in (evidence.summary_metrics or {}).items():
            if k.endswith("_sum") and v is not None:
                raw_col = k[:-4]
                col_name = raw_col.replace("_", " ").title()
                # Skip primary key, foreign key, postal codes, and identifiers from arithmetic totals
                if (
                    raw_col.lower() in ("id", "postal_code", "zip", "zip_code", "year")
                    or raw_col.lower().endswith("_id")
                    or raw_col.lower().endswith("_code")
                ):
                    continue
                dec = DecimalCalculator.to_decimal(v)
                is_monetary = any(m in raw_col.lower() for m in ["salary", "pay", "amount", "price", "total", "revenue", "deduction", "bonus", "budget"])
                val_str = DecimalCalculator.format_currency(dec) if (dec is not None and is_monetary) else str(v)
                sum_notes.append(f"Total {col_name}: {val_str}")
        if sum_notes:
            table_str += f"\n\n**Summary:** {', '.join(sum_notes)}"

        return table_str

    @staticmethod
    def apply_truncation_disclaimer(answer_text: str, truncated: bool) -> str:
        """Append standard truncation disclaimer if query was limited."""
        if not truncated:
            return answer_text
        disclaimer = "\n\n*Note: The database query result was limited to the configured maximum; this result may not represent the complete dataset.*"
        if "*Note: The database query result was limited" not in answer_text:
            return answer_text + disclaimer
        return answer_text
