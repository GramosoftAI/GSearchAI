"""Migration: Add Database Trigger on kb2_entity_values to Reject Sensitive Columns

Second layer of defense directly inside PostgreSQL to ensure sensitive column names
are strictly rejected even on raw SQL inserts or bulk COPY operations.

Revision ID: c3f4d5e6a7b8
Revises: b2f3c4d5e6a7
Create Date: 2026-10-06 13:15:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'c3f4d5e6a7b8'
down_revision = 'b2f3c4d5e6a7'
branch_labels = None
depends_on = None

# SENSITIVE_TOKENS matching knowledge/sensitivity.py
SENSITIVE_TOKENS_SQL = """
    ARRAY[
        'password', 'passwd', 'pwd', 'secret', 'token', 'jwt', 'apikey',
        'key', 'auth', 'privatekey', 'passphrase', 'salt', 'hash',
        'credential', 'pin', 'cvv', 'otp',
        'salary', 'compensation', 'wage', 'creditcard', 'bankaccount',
        'routing', 'iban', 'swift', 'cardnumber',
        'ssn', 'socialsecurity', 'passport', 'nationalid', 'taxid',
        'dob', 'birthdate', 'dateofbirth', 'gender', 'race', 'ethnicity',
        'religion', 'medical', 'health', 'biometric',
        'disciplinary', 'evaluation'
    ]
"""


def upgrade() -> None:
    # 1. Trigger function that splits column_name on delimiters and camelCase, then rejects matches
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
            -- 1. Insert space between lower and upper: aA -> a A
            clean_name := regexp_replace(clean_name, '([a-z])([A-Z])', '\\1 \\2', 'g');
            -- 2. Insert space between upper sequences and next lower: AAa -> A Aa
            clean_name := regexp_replace(clean_name, '([A-Z]+)([A-Z][a-z])', '\\1 \\2', 'g');
            -- 3. Split by non-alphanumeric delimiters
            tokens := regexp_split_to_array(lower(clean_name), '[_\\-\\.\\s]+');

            FOREACH token IN ARRAY tokens LOOP
                IF length(token) > 0 AND token = ANY(sensitive_tokens) THEN
                    RAISE EXCEPTION 'Column "%" contains sensitive token "%" and cannot be stored in kb2_entity_values', NEW.column_name, token
                        USING ERRCODE = 'check_violation';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 2. Attach BEFORE INSERT OR UPDATE trigger on kb2_entity_values
    op.execute("""
        DROP TRIGGER IF EXISTS trg_reject_sensitive_column ON kb2_entity_values;
        CREATE TRIGGER trg_reject_sensitive_column
        BEFORE INSERT OR UPDATE OF column_name ON kb2_entity_values
        FOR EACH ROW
        EXECUTE FUNCTION trg_fn_reject_sensitive_column_entity_values();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_reject_sensitive_column ON kb2_entity_values;")
    op.execute("DROP FUNCTION IF EXISTS trg_fn_reject_sensitive_column_entity_values();")
