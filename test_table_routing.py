import pytest
import re

class MockPipeline:
    class AmbiguousTableError(Exception):
        pass

    def _disambiguate_tables(self, query: str, candidates: list) -> any:
        query_terms = set(re.findall(r'[a-zA-Z0-9]+', query.lower()))
        scored = []
        for kb in candidates:
            col_terms = set()
            schema = kb.dataset_schema or {}
            if "columns" in schema:
                for c in schema["columns"]:
                    col_terms.update(re.findall(r'[a-zA-Z0-9]+', str(c).lower()))
            else:
                for c in schema.keys():
                    col_terms.update(re.findall(r'[a-zA-Z0-9]+', str(c).lower()))
                    
            name_terms = set(re.findall(r'[a-zA-Z0-9]+', str(kb.name or "").lower()))
            overlap = len(query_terms & (col_terms | name_terms))
            scored.append((overlap, kb))
            
        scored.sort(reverse=True, key=lambda x: x[0])
        
        if not scored:
            return None
            
        best_score = scored[0][0]
        
        if best_score == 0:
            raise self.AmbiguousTableError("No table matches query terms.")
            
        top_scorers = [item for item in scored if item[0] == best_score]
        if len(top_scorers) > 1:
            raise self.AmbiguousTableError("Ambiguous tables for query.")
            
        return scored[0][1]


class MockKB:
    def __init__(self, name, schema):
        self.name = name
        self.dataset_schema = schema


def test_disambiguate_tables():
    pipeline = MockPipeline()
    
    # Setup mock candidate tables (e.g. one PDF, one CSV)
    pdf_kb = MockKB(
        name="table (1).pdf", 
        schema={"Disability Category": "string", "Participants": "string", "Accuracy": "string"}
    )
    csv_kb = MockKB(
        name="sales_data.csv", 
        schema={"columns": ["Customer_Type", "Revenue", "Date", "Quantity_Sold", "Product_ID", "Food"]}
    )
    candidates = [pdf_kb, csv_kb]

    # Test 1: Underscore overlap fix (CSV query)
    query1 = "Show me the top 5 best-selling products by quantity sold."
    selected1 = pipeline._disambiguate_tables(query1, candidates)
    assert selected1.name == "sales_data.csv", f"Expected CSV KB, got {selected1.name}"

    print("All regression tests passed!")

if __name__ == "__main__":
    test_disambiguate_tables()
