from typing import List, Dict, Any

class RulesEngine:
    @staticmethod
    def apply_glossary_rules(resolved_entities: List[Dict[str, Any]], original_query: str) -> List[str]:
        """
        Generates strict rules to append to the LLM prompt based on resolved entities
        and query context, preventing hallucinated filtering.
        """
        system_rules: List[str] = []
        
        # 1. ID Resolution Injection
        for entity in resolved_entities:
            if entity.get("type") == "user" and entity.get("id") is not None:
                user_id = entity["id"]
                table_hint = entity.get("table")
                pk_col = entity.get("pk_column") or "id"
                name_hint = entity.get("name", "user")
                
                if isinstance(user_id, list):
                    id_list = ", ".join(f"'{i}'" if isinstance(i, str) else str(i) for i in user_id)
                    if table_hint:
                        system_rules.append(
                            f"RULE: The person '{name_hint}' matches records where {table_hint}.{pk_col} IN ({id_list}). "
                            f"Filter using {table_hint}.{pk_col} IN ({id_list}). "
                            f"Always SELECT the person's name and ID, and GROUP BY them to return separate rows for each person."
                        )
                    else:
                        system_rules.append(
                            f"RULE: The user mentioned in the query matches IDs IN ({id_list}). "
                            f"Filter by ID IN ({id_list}) on the matching user table. "
                            f"Always SELECT the person's name and ID, and GROUP BY them to return separate rows for each person."
                        )
                else:
                    val_repr = f"'{user_id}'" if (isinstance(user_id, str) and not user_id.startswith("'") and not user_id.isdigit()) else user_id
                    if table_hint:
                        system_rules.append(
                            f"RULE: The user '{name_hint}' has {table_hint}.{pk_col} = {val_repr}. "
                            f"Always filter using {table_hint}.{pk_col} = {val_repr} (or the corresponding foreign key column in joined tables, e.g. assigned_to_id = {val_repr}). "
                            f"NEVER filter by display name or login string (like '{name_hint}') because database usernames/logins differ from display names. "
                            f"Never filter an unrelated table's primary key (like employee_employee.id) directly with {table_hint}.{pk_col} values."
                        )
                    else:
                        system_rules.append(
                            f"RULE: The user mentioned in the query has exactly ID = {val_repr}. "
                            f"Filter by ID = {val_repr} on the matching user table."
                        )
            elif entity.get("type") == "user" and entity.get("values"):
                vals = entity.get("values")
                col = entity.get("column") or "name"
                table_hint = entity.get("table")
                name_hint = entity.get("name", "user")
                val_list = ", ".join(f"'{v}'" for v in vals)
                if table_hint:
                    system_rules.append(
                        f"RULE: The user '{name_hint}' matches records where {table_hint}.{col} IN ({val_list})."
                    )
        
        # 2. Assignee vs Author Clarification
        query_lower = original_query.lower()
        if any(term in query_lower for term in ("work package", "work packages", "progress", "task", "tasks")):
            system_rules.append(
                "RULE: When asked for 'work packages' or 'progress' for a user, ALWAYS assume "
                "the user it is assigned to (e.g. work_packages.assigned_to_id = users.id), "
                "UNLESS they explicitly say 'authored by' or 'created by'."
            )
            
        return system_rules
