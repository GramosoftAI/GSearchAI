"""Sensitive Column Deny-List and PII Sanitization

Defines the shared, authoritative list of sensitive column patterns that must NEVER
reveal sample values, distinct value distributions, or be projected in example SQL queries.
Also provides masking utilities for PII fields (email, phone).
"""

import re
from typing import Any, Dict, List, Optional, Set

# Master deny-list for sensitive columns
# (national IDs, salary, DOB, passwords, tokens, card numbers, etc.)
SENSITIVE_COLUMN_PATTERNS: Set[str] = {
    # Credentials & secrets
    "password", "passwd", "pwd", "secret", "token", "jwt", "api_key", "auth_token",
    "private_key", "passphrase", "access_token", "refresh_token", "salt", "hash",
    "credential", "pin", "cvv",
    # Financial & Compensation
    "salary", "compensation", "wage", "credit_card", "card_number", "bank_account",
    "routing_number", "iban", "swift",
    # Personal Identity & Demographics
    "national_id", "ssn", "social_security", "passport", "tax_id",
    "date_of_birth", "dob", "birth_date", "gender", "marital_status",
    # Sensitive Performance & Evaluations
    "performance_rating", "disciplinary_action", "medical_record", "health_condition",
}

# Regex compiler for fast matching
_SENSITIVE_REGEX = re.compile(
    r"(" + "|".join([re.escape(p) for p in SENSITIVE_COLUMN_PATTERNS]) + r")",
    re.IGNORECASE,
)

# Email and phone regexes for sample masking
_EMAIL_REGEX = re.compile(r"([a-zA-Z0-9_.+-]+)@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)")
_PHONE_REGEX = re.compile(r"(\+?[0-9]{1,3}[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}")


class SensitivityGuard:
    """Authority for determining column sensitivity and masking PII values."""

    @classmethod
    def is_sensitive_column(cls, column_name: str) -> bool:
        """
        Check if a column name matches the sensitive column deny-list.
        Case-insensitive and normalizes underscores/hyphens.
        """
        if not column_name:
            return False
        clean_name = column_name.strip().lower().replace("-", "_")
        
        # Exact match or substring match via regex
        if clean_name in SENSITIVE_COLUMN_PATTERNS:
            return True
        if _SENSITIVE_REGEX.search(clean_name):
            return True
        return False

    @classmethod
    def mask_email(cls, email_str: str) -> str:
        """Mask email address (e.g. j***n@example.com)."""
        def _replace_email(match):
            local, domain = match.group(1), match.group(2)
            if len(local) <= 2:
                masked_local = local[0] + "***" if local else "***"
            else:
                masked_local = f"{local[0]}***{local[-1]}"
            return f"{masked_local}@{domain}"
        return _EMAIL_REGEX.sub(_replace_email, email_str)

    @classmethod
    def mask_phone(cls, phone_str: str) -> str:
        """Mask phone number (e.g. ***-***-1234)."""
        def _replace_phone(match):
            raw = match.group(0)
            digits = re.sub(r"\D", "", raw)
            if len(digits) >= 4:
                return f"***-***-{digits[-4:]}"
            return "***-***-****"
        return _PHONE_REGEX.sub(_replace_phone, phone_str)

    @classmethod
    def mask_value(cls, column_name: str, val: Any) -> Any:
        """Apply PII masking to a single column value."""
        if val is None:
            return None
        cname = column_name.lower().strip()
        str_val = str(val)

        # If it's a denied sensitive column, NEVER return any value
        if cls.is_sensitive_column(cname):
            return "[REDACTED_SENSITIVE]"

        # Mask email
        if "email" in cname or "@" in str_val:
            return cls.mask_email(str_val)

        # Mask phone
        if "phone" in cname or "mobile" in cname or "cell" in cname:
            return cls.mask_phone(str_val)

        return val

    @classmethod
    def sanitize_sample_rows(cls, columns: List[str], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sanitizes sample rows before anything goes to LLM:
        - Drops sensitive columns completely from sample dictionary or replaces with [REDACTED]
        - Masks email and phone PII
        """
        sanitized = []
        for r in rows:
            sanitized_row = {}
            for col in columns:
                if cls.is_sensitive_column(col):
                    sanitized_row[col] = "[REDACTED_SENSITIVE]"
                else:
                    raw_val = r.get(col)
                    sanitized_row[col] = cls.mask_value(col, raw_val)
            sanitized.append(sanitized_row)
        return sanitized
