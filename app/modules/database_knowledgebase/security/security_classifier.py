"""Data Security & Column Classification Engine

Maps database schema elements into data classification tiers:
- PUBLIC_DIRECTORY: General corporate directory attributes
- RESTRICTED_PERSONAL: Personally Identifiable Information (PII)
- CONFIDENTIAL_FINANCIAL: Payroll, compensation, and banking data
- SENSITIVE_INTERNAL: Disciplinary, internal reviews, and offboarding data
"""

from enum import Enum
from typing import Dict, List, Optional, Set
from pydantic import BaseModel, ConfigDict


class DataClassification(str, Enum):
    """Classification tiers for database columns."""
    PUBLIC_DIRECTORY = "PUBLIC_DIRECTORY"
    RESTRICTED_PERSONAL = "RESTRICTED_PERSONAL"
    CONFIDENTIAL_FINANCIAL = "CONFIDENTIAL_FINANCIAL"
    SENSITIVE_INTERNAL = "SENSITIVE_INTERNAL"


class SecurityClassificationEngine:
    """Classifies table columns and verifies execution authorization."""

    # Default heuristic classification rules for HR/Enterprise domains
    _CONFIDENTIAL_FINANCIAL_CONCEPTS: Set[str] = {
        "salary", "wage", "basic_salary", "net_pay", "gross_pay", "bonus", "bonus_point",
        "bank_account", "account_number", "ifsc", "iban", "swift", "bank_name",
        "allowance", "deduction", "loan", "reimbursement", "compensation", "payslip",
    }

    _RESTRICTED_PERSONAL_CONCEPTS: Set[str] = {
        "phone", "mobile", "personal_email", "emergency_contact", "emergency_contact_name",
        "emergency_contact_relation", "address", "home_address", "dob", "date_of_birth",
        "marital_status", "children", "passport", "ssn", "national_id",
    }

    _SENSITIVE_INTERNAL_CONCEPTS: Set[str] = {
        "disciplinary", "action_type", "resignation", "resignation_letter",
        "exit_interview", "confidential_feedback", "anonymous_feedback",
    }

    @classmethod
    def classify_column(cls, table_name: str, column_name: str) -> DataClassification:
        """Classify a specific table.column into a security tier."""
        c_low = column_name.lower()
        t_low = table_name.lower()

        # Check financial
        if any(f in c_low for f in ("salary", "wage", "bank", "account_number", "payslip", "allowance", "deduction", "loan", "ifsc", "iban", "swift")):
            return DataClassification.CONFIDENTIAL_FINANCIAL
        if any(f in t_low for f in ("payroll", "bankdetails", "bonuspoint", "payslip")):
            return DataClassification.CONFIDENTIAL_FINANCIAL

        # Check sensitive internal
        if any(s in c_low for s in ("disciplinary", "resignation", "objective", "keyresult", "goal", "rating", "review", "pms", "appraisal")):
            return DataClassification.SENSITIVE_INTERNAL
        if any(s in t_low for s in ("disciplinary", "offboarding", "pms")):
            return DataClassification.SENSITIVE_INTERNAL

        # Check personal PII
        if any(p in c_low for p in ("phone", "mobile", "emergency", "dob", "date_of_birth", "marital", "address")):
            return DataClassification.RESTRICTED_PERSONAL

        return DataClassification.PUBLIC_DIRECTORY

    @classmethod
    def verify_authorization(
        cls,
        table_name: str,
        column_name: str,
        user_role: Optional[str] = None,
        is_admin: bool = False,
    ) -> bool:
        """
        Verify if the caller is authorized to view the requested column.
        Admin / HR Manager has full access.
        Standard users have access to PUBLIC_DIRECTORY and RESTRICTED_PERSONAL (for directory info),
        while CONFIDENTIAL_FINANCIAL and SENSITIVE_INTERNAL require elevated roles.
        """
        if is_admin or user_role in ("admin", "hr_admin", "hr_manager"):
            return True

        classification = cls.classify_column(table_name, column_name)
        if classification in (DataClassification.PUBLIC_DIRECTORY, DataClassification.RESTRICTED_PERSONAL):
            return True

        # Deny confidential financial or sensitive internal to standard users without elevated roles
        return False
