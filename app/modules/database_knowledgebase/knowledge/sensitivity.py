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
    "password", "passwd", "pwd", "secret", "token", "jwt", "apikey", "api_key",
    "privatekey", "private_key", "secretkey", "secret_key", "auth", "passphrase", "salt", "hash",
    "credential", "pin", "cvv", "otp",
    # Financial & Compensation
    "salary", "compensation", "wage", "pay", "income", "creditcard", "bankaccount",
    "routing", "iban", "swift", "cardnumber", "card", "pan",
    "accountnumber",
    # Personal Identifiers & Demographics
    "ssn", "socialsecurity", "passport", "nationalid", "taxid",
    "dob", "birthdate", "dateofbirth", "gender", "race", "ethnicity",
    "religion", "medical", "health", "biometric",
    # Performance & Disciplinary
    "disciplinary", "evaluation",
}

# PII deny-list tokens specifically sensitive for values (no top_values, no value index, no values to LLM)
PII_VALUE_TOKENS: Set[str] = {
    "email", "mail", "phone", "phonenumber", "telephone", "mobile", "cell",
    "address", "street", "city", "zipcode", "postal", "postalcode",
    "dob", "birthdate", "dateofbirth",
    "nationalid", "ssn", "passport", "taxid", "aadhaar", "pan",
    "ip", "ipaddress",
}

# Regex to split on underscores, hyphens, dots, spaces, or camelCase transitions
_TOKEN_SPLIT_REGEX = re.compile(
    r"[_\-.\s]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)


def is_pii_column(column_name: str) -> bool:
    """Check if column_name contains any PII token sensitive for value extraction/indexing."""
    if not column_name:
        return False
    raw = str(column_name).strip()
    if not raw:
        return False
    tokens = [t.lower() for t in _TOKEN_SPLIT_REGEX.split(raw) if t]
    for token in tokens:
        if token in PII_VALUE_TOKENS:
            return True
    compact = re.sub(r"[^a-zA-Z0-9]", "", raw).lower()
    if compact in PII_VALUE_TOKENS:
        return True
    return False


def is_sensitive_for_values(column_name: str) -> bool:
    """Check if column is either generally sensitive or PII-sensitive for values."""
    return is_sensitive_column(column_name) or is_pii_column(column_name)


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

    # Ensure numeric amounts, integers, decimals, and dates are not falsely flagged as phones
    if re.match(r"^-?\d+(?:\.\d+)?$", val_str):
        return False

    if 10 <= len(clean_digits) <= 15 and ("-" in val_str or " " in val_str or "+" in val_str or "(" in val_str):
        if _PHONE_REGEX.match(val_str):
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
