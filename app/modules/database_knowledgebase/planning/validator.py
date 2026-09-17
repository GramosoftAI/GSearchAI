"""Query Plan IR Validator

Validates QueryPlanIR against canonical DatabaseSchema and SchemaGraph.
Guarantees that no query plan invents tables, columns, or non-existent relational join paths.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from ..exceptions import QueryPlanError, SchemaVersionMismatchError
from ..schemas.canonical import DatabaseSchema, RelationshipType
from ..schema.graph import SchemaGraph
from .models import QueryPlanIR, TablePlan, JoinPlan, ColumnProjectionPlan, PredicatePlan, AggregateFunction

logger = logging.getLogger(__name__)


class QueryPlanValidationError(QueryPlanError):
    """Raised when a QueryPlanIR fails canonical validation."""
    pass


class QueryPlanValidator:
    """
    Deterministically validates QueryPlanIR against trusted canonical DatabaseSchema.
    """

    @classmethod
    def validate_plan(
        cls,
        plan: QueryPlanIR,
        canonical_schema: DatabaseSchema,
        expected_entities: Optional[List[str]] = None,
        resolved_entities: Optional[List[Any]] = None,
    ) -> None:
        """
        Validate all structural aspects of QueryPlanIR against canonical_schema.
        
        Raises:
            QueryPlanValidationError or SchemaVersionMismatchError on any violation.
        """
        # 1. Schema Version Check
        if canonical_schema.fingerprint and plan.schema_version != canonical_schema.fingerprint:
            raise SchemaVersionMismatchError(
                f"Query plan schema version '{plan.schema_version}' does not match active snapshot '{canonical_schema.fingerprint}'"
            )

        # 2. Table Existence & Alias Map
        alias_to_table: Dict[str, Tuple[str, str]] = {}  # alias -> (schema_name, table_name)
        seen_aliases: Set[str] = set()

        for tbl in plan.tables:
            if tbl.alias in seen_aliases:
                raise QueryPlanValidationError(f"Duplicate table alias '{tbl.alias}' in query plan")
            seen_aliases.add(tbl.alias)

            s_info = canonical_schema.get_schema(tbl.schema_name)
            if not s_info:
                raise QueryPlanValidationError(
                    f"Schema namespace '{tbl.schema_name}' does not exist in canonical database"
                )
            if tbl.table_name not in s_info.tables:
                raise QueryPlanValidationError(
                    f"Table '{tbl.schema_name}.{tbl.table_name}' does not exist in canonical schema"
                )

            alias_to_table[tbl.alias] = (tbl.schema_name, tbl.table_name)

        # Fail-closed guard: if plan confidence is 0.0 and no projections, it's an intentional fail-closed plan
        if plan.confidence == 0.0 and not plan.projections:
            return

        # 3. Validate Projections (SELECT columns)
        for proj in plan.projections:
            if proj.table_alias not in alias_to_table:
                raise QueryPlanValidationError(
                    f"Projection references unknown table alias '{proj.table_alias}'"
                )
            s_name, t_name = alias_to_table[proj.table_alias]
            table = canonical_schema.get_schema(s_name).tables[t_name]

            # Allow wildcard '*', existing column, or calculated expression whose referenced columns exist
            if proj.column_name != "*" and proj.column_name not in table.columns:
                valid_calc = False
                try:
                    import sqlglot
                    from sqlglot import exp
                    parsed_expr = sqlglot.parse_one(proj.column_name, read="postgres")
                    cols = [c.name.lower() for c in parsed_expr.find_all(exp.Column)]
                    if cols and all(c in {col.lower() for col in table.columns.keys()} for c in cols):
                        valid_calc = True
                except Exception:
                    pass

                if not valid_calc:
                    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", proj.column_name)
                    SQL_KEYWORDS = {
                        "sum", "avg", "count", "min", "max", "round", "cast", "nullif", "as",
                        "numeric", "decimal", "integer", "coalesce", "least", "greatest",
                        "date_trunc", "current_date", "current_timestamp", "now", "interval",
                        "month", "year", "day", "date", "case", "when", "then", "else", "end",
                        "extract", "dow"
                    }
                    col_words = [w for w in words if w.lower() not in SQL_KEYWORDS]
                    if not col_words or not all(w in table.columns for w in col_words):
                        raise QueryPlanValidationError(
                            f"Column '{proj.column_name}' does not exist on table '{s_name}.{t_name}'"
                        )

        # 3.1 Projection Data Minimization & Sensitive Attributes Guard (Fail-Closed)
        SENSITIVE_FINANCIAL = {
            "basic_salary", "salary", "wage", "gross_pay", "net_pay", "basic_pay",
            "deduction", "allowance", "bonus", "hourly_rate", "payment_rate",
            "salary_hour", "revised_salary", "asset_purchase_cost", "purchase_cost",
            "cost", "price"
        }
        SENSITIVE_BANKING = {"bank_name", "account_number", "routing_number", "iban", "swift", "branch", "ifsc"}
        SENSITIVE_CONTACT = {"phone", "mobile", "telephone", "emergency_contact", "contact_number"}
        SENSITIVE_PII = {"dob", "date_of_birth", "age", "marital_status", "children", "passport_number", "ssn", "national_id"}
        SENSITIVE_LOCATION = {"address", "address_line", "postal_code", "zip_code"}
        SENSITIVE_CREDENTIALS = {"password", "secret", "token", "hash", "salt"}
        MEDIA_KEYWORDS = ("image", "photo", "picture", "avatar", "attachment", "document", "file", "blob")

        q_low = plan.user_query.lower()

        is_fin_auth = any(w in q_low for w in ("salary", "wage", "earn", "earning", "make", "compensation", "payslip", "deduction", "allowance", "bonus", "gross pay", "net pay", "basic pay", "pay", "income", "basic_salary"))
        if is_fin_auth and any(w in q_low for w in ("show employees", "list employees", "which employees", "who are the employees", "employees in", "all employees")):
            if any(kw in q_low for kw in ("whose salary", "with salary", "salary >", "salary above", "salary <", "salary less", "salary greater")):
                if not any(ask in q_low for ask in ("and their salary", "with their salary", "show salary", "what is their salary")):
                    is_fin_auth = False

        has_cost_intent = any(w in q_low for w in ("cost", "price", "how much", "amount", "worth", "value", "expensive", "cheap"))
        has_media_intent = any(w in q_low for w in ("image", "photo", "picture", "avatar", "attachment", "document", "file", "download", "view image", "show picture"))

        is_phone_auth = any(w in q_low for w in ("phone", "mobile", "cell", "telephone", "call", "contact number"))
        if is_phone_auth and "whose phone" in q_low and "available" in q_low and not any(ask in q_low for ask in ("show phone", "what is", "and their phone")):
            is_phone_auth = False

        is_email_auth = any(w in q_low for w in ("email", "mail address", "send email", "email address", "where can i email"))
        is_dob_auth = any(w in q_low for w in ("dob", "birth", "birthday", "born", "age", "how old"))
        is_pii_auth = any(w in q_low for w in ("marital", "married", "single", "spouse", "children", "kids", "child", "qualification", "degree"))
        is_loc_auth = any(w in q_low for w in ("address", "where does", "where is", "live", "residence"))
        is_bank_auth = any(w in q_low for w in ("bank", "account number", "iban", "routing", "swift", "ifsc"))

        for proj in plan.projections:
            col_low = proj.column_name.lower()
            if proj.aggregation not in (AggregateFunction.NONE, None):
                continue

            if col_low in SENSITIVE_CREDENTIALS:
                raise QueryPlanValidationError(
                    f"Projection security violation: Credentials column '{proj.column_name}' must never be projected [SECURITY_CRITICAL]"
                )
            if any(m in col_low for m in MEDIA_KEYWORDS) and not has_media_intent:
                raise QueryPlanValidationError(
                    f"Projection security violation: Unrequested media attachment '{proj.table_alias}.{proj.column_name}' cannot be projected [DATA_MINIMIZATION_VIOLATION]"
                )
            if (col_low in SENSITIVE_FINANCIAL or any(s in col_low for s in ("salary", "wage"))) and not (is_fin_auth or has_cost_intent):
                raise QueryPlanValidationError(
                    f"Projection security violation: Unrequested financial column '{proj.table_alias}.{proj.column_name}' cannot be projected [DATA_MINIMIZATION_VIOLATION]"
                )
            if col_low in SENSITIVE_CONTACT and not (is_phone_auth if col_low != "email" else is_email_auth):
                raise QueryPlanValidationError(
                    f"Projection security violation: Unrequested contact column '{proj.table_alias}.{proj.column_name}' cannot be projected [DATA_MINIMIZATION_VIOLATION]"
                )
            if col_low in SENSITIVE_PII and not (is_dob_auth if col_low in ("dob", "date_of_birth", "age") else is_pii_auth):
                raise QueryPlanValidationError(
                    f"Projection security violation: Unrequested PII column '{proj.table_alias}.{proj.column_name}' cannot be projected [DATA_MINIMIZATION_VIOLATION]"
                )
            if col_low in SENSITIVE_LOCATION and not is_loc_auth:
                raise QueryPlanValidationError(
                    f"Projection security violation: Unrequested location column '{proj.table_alias}.{proj.column_name}' cannot be projected [DATA_MINIMIZATION_VIOLATION]"
                )
            if col_low in SENSITIVE_BANKING and not is_bank_auth:
                raise QueryPlanValidationError(
                    f"Projection security violation: Unrequested banking column '{proj.table_alias}.{proj.column_name}' cannot be projected [DATA_MINIMIZATION_VIOLATION]"
                )

        # 4. Validate Predicates (WHERE filters)
        for pred in plan.predicates:
            if pred.table_alias not in alias_to_table:
                raise QueryPlanValidationError(
                    f"Predicate references unknown table alias '{pred.table_alias}'"
                )
            s_name, t_name = alias_to_table[pred.table_alias]
            table = canonical_schema.get_schema(s_name).tables[t_name]

            if pred.column_name not in table.columns:
                raise QueryPlanValidationError(
                    f"Predicate column '{pred.column_name}' does not exist on table '{s_name}.{t_name}'"
                )

        # 5. Validate Joins
        graph = SchemaGraph.from_database_schema(canonical_schema)

        for join in plan.joins:
            if join.source_table_alias not in alias_to_table:
                raise QueryPlanValidationError(
                    f"Join source references unknown table alias '{join.source_table_alias}'"
                )
            if join.target_table_alias not in alias_to_table:
                raise QueryPlanValidationError(
                    f"Join target references unknown table alias '{join.target_table_alias}'"
                )

            src_s, src_t = alias_to_table[join.source_table_alias]
            tgt_s, tgt_t = alias_to_table[join.target_table_alias]

            src_table = canonical_schema.get_schema(src_s).tables[src_t]
            tgt_table = canonical_schema.get_schema(tgt_s).tables[tgt_t]

            # Verify columns exist
            if join.source_column not in src_table.columns:
                raise QueryPlanValidationError(
                    f"Join source column '{join.source_column}' does not exist on '{src_s}.{src_t}'"
                )
            if join.target_column not in tgt_table.columns:
                raise QueryPlanValidationError(
                    f"Join target column '{join.target_column}' does not exist on '{tgt_s}.{tgt_t}'"
                )

            # Verify relationship is authorized in canonical schema graph
            src_key = f"{src_s}.{src_t}"
            tgt_key = f"{tgt_s}.{tgt_t}"
            rels = [rel for neighbor, rel in graph.get_neighbors(src_key) if neighbor == tgt_key]

            if not rels:
                raise QueryPlanValidationError(
                    f"Unauthorized join between '{src_key}' and '{tgt_key}': no canonical foreign key relationship exists"
                )

            # Verify join columns match at least one approved relationship definition
            valid_join = False
            for rel in rels:
                if (
                    (join.source_column in rel.source_columns and join.target_column in rel.target_columns)
                    or (join.source_column in rel.target_columns and join.target_column in rel.source_columns)
                ):
                    valid_join = True
                    break

            if not valid_join:
                raise QueryPlanValidationError(
                    f"Join condition '{src_t}.{join.source_column} = {tgt_t}.{join.target_column}' does not match canonical foreign key definitions"
                )

        # 6. Anti-Cartesian Check (All planned tables must be connected if count > 1)
        if len(plan.tables) > 1:
            joined_aliases = set()
            for join in plan.joins:
                joined_aliases.add(join.source_table_alias)
                joined_aliases.add(join.target_table_alias)

            unjoined = set(alias_to_table.keys()) - joined_aliases
            if unjoined:
                raise QueryPlanValidationError(
                    f"Cartesian product detected: table aliases {unjoined} are not joined to any other table"
                )

        # 7. Multi-Entity Semantic Completeness Check (Phase 6.5 & Schema-Grounded)
        if resolved_entities is not None:
            high_tables = [
                r for r in resolved_entities
                if getattr(r, "confidence", None) == "HIGH"
                and getattr(r, "entity_type", None) == "TABLE"
                and not getattr(r, "metadata", {}).get("is_ngram")
                and not getattr(r, "metadata", {}).get("likely_verb")
            ]
            if len(high_tables) >= 2:
                single_table_covers_all = False
                for t in plan.tables:
                    t_tokens = set(t.table_name.lower().split("_"))
                    ext_tokens = set(t_tokens)
                    for tok in t_tokens:
                        if tok.endswith("s") and len(tok) > 3:
                            ext_tokens.add(tok[:-1])
                    if all(
                        any(
                            r.token.lower() == tok
                            or r.token.lower() in tok
                            or tok in r.token.lower()
                            or r.token.lower().replace("_", "") in t.table_name.lower().replace("_", "")
                            for tok in ext_tokens
                        )
                        for r in high_tables
                    ):
                        single_table_covers_all = True
                        break

                if not single_table_covers_all:
                    if len(plan.tables) < 2 or len(plan.joins) == 0:
                        logger.warning(
                            f"Semantic plan notice: Multi-entity query expected tables for {[r.token for r in high_tables]}, plan contains {[t.table_name for t in plan.tables]}"
                        )
        elif expected_entities and len(expected_entities) >= 2:
            # Check if all expected entities are satisfied by a single compound table in the plan
            single_table_covers_all = False
            for t in plan.tables:
                t_tokens = set(t.table_name.lower().split("_"))
                # Also include stripped/singular tokens
                ext_tokens = set(t_tokens)
                for tok in t_tokens:
                    if tok.endswith("s") and len(tok) > 3:
                        ext_tokens.add(tok[:-1])
                if all(
                    any(
                        e.lower() == tok
                        or e.lower() in tok
                        or tok in e.lower()
                        or e.lower().replace("_", "") in t.table_name.lower().replace("_", "")
                        for tok in ext_tokens
                    )
                    for e in expected_entities
                ):
                    single_table_covers_all = True
                    break

            if not single_table_covers_all:
                if len(plan.tables) < 2 or len(plan.joins) == 0:
                    logger.warning(
                        f"Semantic plan notice: Multi-entity query expected entities {expected_entities}, plan contains {[t.table_name for t in plan.tables]}"
                    )
