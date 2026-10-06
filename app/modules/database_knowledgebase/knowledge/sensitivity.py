"""Phase 2 Knowledge Layer: Sensitivity Guard

Authoritative check for identifying sensitive columns that must be strictly rejected
from entity value extraction and storage.
Uses token-based matching (splitting camelCase, kebab-case, snake_case).
Does NOT do arbitrary raw substring matching to avoid false positives (e.g. 'asset_token' vs 'token').
"""

import re
from typing import Set, Any, List

# Standard deny-list tokens (normalized to lowercase)
SENSITIVE_TOKENS: Set[str] = {
    # Credentials & Secrets
    "password", "passwd", "pwd", "secret", "token", "jwt", "apikey",
    "key", "auth", "privatekey", "passphrase", "salt", "hash",
    "credential", "pin", "cvv", "otp",
    # Financial & Compensation
    "salary", "compensation", "wage", "creditcard", "bankaccount",
    "routing", "iban", "swift", "cardnumber", "card", "pan",
    "accountnumber",
    # Personal Identifiers & Demographics
    "ssn", "socialsecurity", "passport", "nationalid", "taxid",
    "dob", "birthdate", "dateofbirth", "gender", "race", "ethnicity",
    "religion", "medical", "health", "biometric",
    # Performance & Disciplinary
    "disciplinary", "evaluation",
}

# Regex to split on underscores, hyphens, dots, spaces, or camelCase transitions
_TOKEN_SPLIT_REGEX = re.compile(
    r"[_\-.\s]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def is_sensitive_column(column_name: str) -> bool:
    """Check if column_name contains any sensitive token.

    Splits the identifier into constituent words (supporting snake_case,
    camelCase, PascalCase, kebab-case) and checks each token against
    the sensitive deny-list.

    Examples:
        is_sensitive_column("user_password") -> True
        is_sensitive_column("passwordHash") -> True
        is_sensitive_column("salary") -> True
        is_sensitive_column("card_number_masked") -> True
        is_sensitive_column("account_number") -> True
        is_sensitive_column("employee_status") -> False
        is_sensitive_column("order_total") -> False
    """
    if not column_name:
        return False

    raw = str(column_name).strip()
    if not raw:
        return False

    tokens = [t.lower() for t in _TOKEN_SPLIT_REGEX.split(raw) if t]
    for token in tokens:
        if token in SENSITIVE_TOKENS:
            return True

    # Also test whole stripped alphanumeric representation if compound (e.g. "apikey", "passcode", "accountnumber")
    compact = re.sub(r"[^a-zA-Z0-9]", "", raw).lower()
    if compact in SENSITIVE_TOKENS:
        return True

    return False


# ==============================================================================
# Value Pattern Detection for Tiny Sample Checks
# ==============================================================================

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_PHONE_REGEX = re.compile(r"^\+?[0-9]{1,4}?[-.\s]?\(?[0-9]{1,4}?\)?[-.\s]?[0-9]{1,4}[-.\s]?[0-9]{1,9}$")
_CREDIT_CARD_REGEX = re.compile(r"^(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:2131|1800|35\d{3})\d{11})$")
_MASKED_CARD_REGEX = re.compile(r"^\d{4,6}[*xX\-_]{4,12}\d{3,4}$")
_LONG_RANDOM_TOKEN_REGEX = re.compile(r"^[A-Za-z0-9+/=_~-]{32,}$")


def is_sensitive_value(value: Any) -> bool:
    """Check if a sample value matches high-risk PII/secret patterns."""
    if value is None:
        return False
    val_str = str(value).strip()
    if not val_str or len(val_str) > 1024:
        return False

    if _EMAIL_REGEX.match(val_str):
        return True

    if _MASKED_CARD_REGEX.match(val_str):
        return True

    clean_digits = re.sub(r"[^\d]", "", val_str)
    if 13 <= len(clean_digits) <= 19 and _CREDIT_CARD_REGEX.match(clean_digits):
        return True

    if len(clean_digits) >= 10 and _PHONE_REGEX.match(val_str):
        return True

    if _LONG_RANDOM_TOKEN_REGEX.match(val_str) and any(c.isdigit() for c in val_str) and any(c.isalpha() for c in val_str):
        return True

    return False


def check_values_sensitivity(sample_values: list) -> bool:
    """Return True if any value in sample_values triggers sensitivity detection."""
    for val in sample_values:
        if is_sensitive_value(val):
            return True
    return False


def validate_not_sensitive(column_name: str) -> None:
    """Validate that a column is not sensitive; raise ValueError if it is.

    Use this at write-time or in batch/bulk insertion pipelines.
    """
    if is_sensitive_column(column_name):
        raise ValueError(
            f"Column '{column_name}' is identified as sensitive and cannot be stored in entity values."
        )
