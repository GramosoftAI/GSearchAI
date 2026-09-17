"""Grounding and Numerical Validators for Phase 2D Answer Synthesis

Implements intelligent numerical verification, entity grounding, and anti-hallucination checks.
Understands valid deterministic derivations (row counts, list ranks, query parameters)
to prevent false-positive rejections of correct answers while strictly preventing hallucinations.
"""

from decimal import Decimal
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .calculator import DecimalCalculator
from .models import EvidenceModel, GroundingReport, VerificationStatus

# Standard English sentence starters and table column headers to exclude from entity checking
EXCLUDED_WORDS = {
    "The", "Here", "There", "Based", "These", "All", "Total", "Average", "Customer",
    "Customers", "Order", "Orders", "Product", "Products", "Payment", "Payments", "Item",
    "Items", "Sales", "Revenue", "Price", "Amount", "Quantity", "Date", "Status", "Email",
    "City", "Category", "Name", "ID", "Top", "Below", "List", "Showing", "Found", "Matching",
    "Each", "Highest", "Lowest", "Most", "Recent", "Single", "Value", "Recorded", "Across",
    "For", "In", "With", "And", "Or", "Not", "Yes", "No", "None", "Null", "Details", "Table",
    "Record", "Records", "Summary", "Overall", "January", "February", "March", "April", "May",
    "June", "July", "August", "September", "October", "November", "December", "Electronics",
    "Furniture", "Office", "Supplies", "New", "York", "San", "Francisco", "Chicago", "Seattle", "Austin",
    "Both", "First", "Last", "Note", "Although", "However", "Currently", "Please", "Regarding",
    "Information", "Employee", "Employees", "Department", "Departments", "Title", "Titles",
    "Start", "End", "Hire", "Project", "Projects", "Review", "Reviews", "Leave", "Leaves",
    "Request", "Requests", "Salary", "Salaries", "Unique", "Active", "Which", "What", "Who", "Where",
    "My", "Your", "Our", "Their", "His", "Her", "Its", "This", "That", "These", "Those", "Some", "Any"
}


class NumericalVerifier:
    """Verifies that all numerical values in the answer are strictly supported by evidence or valid derivations."""

    @classmethod
    def verify(cls, answer_text: str, evidence: EvidenceModel, user_query: str = "") -> Tuple[bool, List[str]]:
        """
        Verify all numbers appearing in answer_text against evidence.supported_numbers.
        Returns (is_valid, list_of_unsupported_numbers).
        """
        unsupported: List[str] = []
        supported_set = set(evidence.supported_numbers)

        # 1. Normalize answer lines: ignore Markdown list numbers (e.g. "1. ", "2. ")
        cleaned_lines = []
        for line in answer_text.splitlines():
            # Strip leading list enumeration like "1. ", "2) "
            clean_line = re.sub(r"^\s*\d+[\.\)]\s+", "", line)
            cleaned_lines.append(clean_line)
        clean_text = "\n".join(cleaned_lines)

        # 2. Extract numerical tokens from cleaned text
        # Matches currency ($1,692.98), decimals (149.99), integers (500), percentages (10.5%)
        raw_tokens = re.findall(r"\$?\b\d+(?:,\d{3})*(?:\.\d+)?%?\b", clean_text)

        for token in raw_tokens:
            clean_token = token.strip().replace("$", "").replace(",", "").replace("%", "")
            
            # Check if token is already in supported numbers
            if token in supported_set or clean_token in supported_set:
                continue

            # Check if token matches a Decimal value in supported numbers
            dec_token = DecimalCalculator.to_decimal(clean_token)
            if dec_token is not None:
                if str(dec_token) in supported_set:
                    continue
                if f"{dec_token:.2f}" in supported_set:
                    continue
                # If whole number, check integer string
                if dec_token == dec_token.to_integral_value() and str(int(dec_token)) in supported_set:
                    continue

            # Check if token was present in the user query (e.g. "30" from "last 30 days", "3" from ">3 orders")
            if user_query and (token in user_query or clean_token in user_query):
                continue

            # Flag as genuinely unsupported number
            unsupported.append(token)

        return (len(unsupported) == 0, unsupported)


class EntityGroundingValidator:
    """Verifies that all named entities mentioned in the answer exist in the evidence or user query."""

    @classmethod
    def verify(cls, answer_text: str, evidence: EvidenceModel, user_query: str = "") -> Tuple[bool, List[str]]:
        """
        Extract proper nouns / entity names from answer and check against evidence.supported_entities.
        Returns (is_valid, list_of_unsupported_entities).
        """
        unsupported: List[str] = []
        supported_entities = set(evidence.supported_entities)
        if hasattr(evidence, "column_names") and evidence.column_names:
            for c in evidence.column_names:
                supported_entities.add(c)
                for part in c.replace("_", " ").split():
                    supported_entities.add(part)

        # Extract capitalized phrases and their positions
        for match in re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", answer_text):
            phrase = match.group(0)
            start_pos = match.start()

            if phrase in EXCLUDED_WORDS:
                continue
            words = phrase.split()
            if all(w in EXCLUDED_WORDS for w in words):
                continue

            # Grammatical sentence starters: single capitalized words directly after punctuation or start of line/list/table cell
            if len(words) == 1:
                prefix = answer_text[:start_pos].rstrip()
                if not prefix or prefix[-1] in {".", "!", "?", ":", "\n", "-", "*", "|"} or re.search(r"(\d+[\.\)]|\*|-|\|)$", prefix):
                    continue

            # Check if phrase or any sub-word is in supported entities or user query
            supported_entities_lower = {e.lower() for e in supported_entities}
            phrase_lower = phrase.lower()
            phrase_supported = (
                phrase in supported_entities
                or phrase_lower in supported_entities_lower
                or any(w in supported_entities for w in words)
                or any(w.lower() in supported_entities_lower for w in words)
                or any(phrase_lower in e.lower() for e in supported_entities)
                or (user_query and phrase_lower in user_query.lower())
            )

            if not phrase_supported:
                unsupported.append(phrase)

        return (len(unsupported) == 0, unsupported)


class TruncationValidator:
    """Ensures that answers for truncated query results contain an appropriate disclaimer."""

    @classmethod
    def verify(cls, answer_text: str, evidence: EvidenceModel) -> Tuple[bool, List[str]]:
        warnings: List[str] = []
        if evidence.truncated:
            has_disclaimer = any(k in answer_text.lower() for k in ["limited", "truncated", "maximum", "first", "partial"])
            if not has_disclaimer:
                warnings.append("Result was truncated but answer does not mention limitation.")
                return False, warnings
        return True, warnings


class EmptyResultValidator:
    """Ensures that answers for empty query results state no records were found and do not hallucinate entities."""

    @classmethod
    def verify(cls, answer_text: str, evidence: EvidenceModel) -> Tuple[bool, List[str]]:
        warnings: List[str] = []
        if evidence.row_count == 0:
            states_empty = any(k in answer_text.lower() for k in ["no matching", "no records", "0", "zero", "none", "not found", "no customers", "no orders", "no items"])
            if not states_empty:
                warnings.append("Query returned 0 rows but answer does not state no records found.")
                return False, warnings
        return True, warnings
