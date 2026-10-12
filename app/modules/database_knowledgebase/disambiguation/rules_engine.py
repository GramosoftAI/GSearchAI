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
            if entity.get("type") == "user" and "id" in entity:
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
                    if table_hint:
                        system_rules.append(
                            f"RULE: The user '{name_hint}' has {table_hint}.{pk_col} = {user_id}. "
                            f"If querying '{table_hint}' or tables joining to '{table_hint}' (e.g. employee_user_id_id = {table_hint}.{pk_col}), "
                            f"filter by that exact ID column. If querying another table that has its own primary key, join appropriately or filter by name string. "
                            f"Never filter an unrelated table's primary key (like employee_employee.id) directly with {table_hint}.{pk_col} values."
                        )
                    else:
                        system_rules.append(
                            f"RULE: The user mentioned in the query has exactly ID = {user_id}. "
                            f"Filter by ID = {user_id} on the matching user table."
                        )
        
        # 2. Assignee vs Author Clarification
        query_lower = original_query.lower()
        if "work package" in query_lower or "work packages" in query_lower:
            system_rules.append(
                "RULE: When asked for 'work packages for [User]', ALWAYS assume they mean "
                "the user it is assigned to, UNLESS they explicitly say 'authored by' or 'created by'."
            )
            
        return system_rules
