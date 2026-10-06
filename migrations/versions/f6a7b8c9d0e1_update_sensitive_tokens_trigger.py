"""Migration: Update Sensitive Column Trigger to Include Card, PAN, and Account Number Tokens

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-06 17:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None

# SENSITIVE_TOKENS matching knowledge/sensitivity.py
SENSITIVE_TOKENS_SQL = """
    ARRAY[
        'password', 'passwd', 'pwd', 'secret', 'token', 'jwt', 'apikey',
        'key', 'auth', 'privatekey', 'passphrase', 'salt', 'hash',
        'credential', 'pin', 'cvv', 'otp',
        'salary', 'compensation', 'wage', 'creditcard', 'bankaccount',
        'routing', 'iban', 'swift', 'cardnumber', 'card', 'pan',
        'accountnumber',
        'ssn', 'socialsecurity', 'passport', 'nationalid', 'taxid',
        'dob', 'birthdate', 'dateofbirth', 'gender', 'race', 'ethnicity',
        'religion', 'medical', 'health', 'biometric',
        'disciplinary', 'evaluation'
    ]
"""


def upgrade() -> None:
    # Update trigger function with the augmented token set
    op.execute(f"""
        CREATE OR REPLACE FUNCTION trg_fn_reject_sensitive_column_entity_values()
        RETURNS TRIGGER AS $$
        DECLARE
            clean_name TEXT;
            normalized_compact TEXT;
            token TEXT;
            tokens TEXT[];
            sensitive_tokens TEXT[] := {SENSITIVE_TOKENS_SQL};
        BEGIN
            IF NEW.column_name IS NULL OR length(trim(NEW.column_name)) = 0 THEN
                RETURN NEW;
            END IF;

            clean_name := trim(NEW.column_name);

            -- Check compound alphanumeric representation without non-alphanumerics
            normalized_compact := lower(regexp_replace(clean_name, '[^a-zA-Z0-9]', '', 'g'));
            IF normalized_compact = ANY(sensitive_tokens) THEN
                RAISE EXCEPTION 'Column "%" is identified as sensitive and cannot be stored in kb2_entity_values', NEW.column_name
                    USING ERRCODE = 'check_violation';
            END IF;

            -- Tokenize by inserting space at camelCase boundaries, then splitting by [_\-.\s]+
            tokens := regexp_split_to_array(
                lower(
                    regexp_replace(
                        regexp_replace(clean_name, '([a-z])([A-Z])', '\\1 \\2', 'g'),
                        '([A-Z])([A-Z][a-z])',
                        '\\1 \\2',
                        'g'
                    )
                ),
                '[_\-.\s]+'
            );

            FOREACH token IN ARRAY tokens LOOP
                IF length(token) > 0 AND token = ANY(sensitive_tokens) THEN
                    RAISE EXCEPTION 'Column "%" matches sensitive token "%" and cannot be stored in kb2_entity_values', NEW.column_name, token
                        USING ERRCODE = 'check_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Revert to original revision tokens
    from migrations.versions.c3f4d5e6a7b8_add_sensitive_column_trigger import SENSITIVE_TOKENS_SQL as OLD_TOKENS_SQL
    op.execute(f"""
        CREATE OR REPLACE FUNCTION trg_fn_reject_sensitive_column_entity_values()
        RETURNS TRIGGER AS $$
        DECLARE
            clean_name TEXT;
            normalized_compact TEXT;
            token TEXT;
            tokens TEXT[];
            sensitive_tokens TEXT[] := {OLD_TOKENS_SQL};
        BEGIN
            IF NEW.column_name IS NULL OR length(trim(NEW.column_name)) = 0 THEN
                RETURN NEW;
            END IF;

            clean_name := trim(NEW.column_name);
            normalized_compact := lower(regexp_replace(clean_name, '[^a-zA-Z0-9]', '', 'g'));
            IF normalized_compact = ANY(sensitive_tokens) THEN
                RAISE EXCEPTION 'Column "%" is identified as sensitive and cannot be stored in kb2_entity_values', NEW.column_name
                    USING ERRCODE = 'check_violation';
            END IF;

            tokens := regexp_split_to_array(
                lower(
                    regexp_replace(
                        regexp_replace(clean_name, '([a-z])([A-Z])', '\\1 \\2', 'g'),
                        '([A-Z])([A-Z][a-z])',
                        '\\1 \\2',
                        'g'
                    )
                ),
                '[_\-.\s]+'
            );

            FOREACH token IN ARRAY tokens LOOP
                IF length(token) > 0 AND token = ANY(sensitive_tokens) THEN
                    RAISE EXCEPTION 'Column "%" matches sensitive token "%" and cannot be stored in kb2_entity_values', NEW.column_name, token
                        USING ERRCODE = 'check_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
