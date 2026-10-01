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
                if isinstance(user_id, list):
                    id_list = ", ".join(f"'{i}'" if isinstance(i, str) else str(i) for i in user_id)
                    system_rules.append(
                        f"RULE: The user mentioned in the query matches IDs IN ({id_list}). "
                        f"Do NOT search by name strings. Always use ID IN ({id_list}) when filtering users."
                    )
                else:
                    system_rules.append(
                        f"RULE: The user mentioned in the query has exactly ID = {user_id}. "
                        f"Do NOT search by name strings. Always use ID {user_id} when filtering users."
                    )
        
        # 2. Assignee vs Author Clarification
        query_lower = original_query.lower()
        if "work package" in query_lower or "work packages" in query_lower:
            system_rules.append(
                "RULE: When asked for 'work packages for [User]', ALWAYS assume they mean "
                "the user it is assigned to, UNLESS they explicitly say 'authored by' or 'created by'."
            )
            
        return system_rules
