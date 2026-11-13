import pytest
from app.modules.rag.scoring.term_frequency import idf_discount

def test_tongaat_revenue_collision_penalty():
    """
    Test 1: Tongaat revenue case.
    Generic table terms ('2021', 'total') should have low IDF,
    while specific terms ('revenue') should have high IDF.
    """
    doc_freq = {
        "_total_chunks": 100,
        "2021": 95,
        "total": 90,
        "revenue": 2
    }
    
    # Generic terms should be penalized near the floor (0.15)
    assert idf_discount("2021", doc_freq) < 0.2
    assert idf_discount("total", doc_freq) < 0.2
    
    # Specific term should retain high score
    assert idf_discount("revenue", doc_freq) > 0.8

def test_apple_ntsb_collision_penalty():
    """
    Test 2: Apple 10-K vs NTSB collision.
    """
    doc_freq = {
        "_total_chunks": 500,
        "the": 490,  # stopword
        "probable": 5,
        "cause": 5
    }
    
    assert idf_discount("the", doc_freq) < 0.2
    assert idf_discount("probable", doc_freq) > 0.8
    assert idf_discount("cause", doc_freq) > 0.8

def test_hr_csv_sales_data_collision():
    """
    Test 3: HR-CSV vs Sales Data numeric collision.
    """
    doc_freq = {
        "_total_chunks": 200,
        "department": 150,
        "sales": 10
    }
    assert idf_discount("department", doc_freq) < 0.3
    assert idf_discount("sales", doc_freq) > 0.8

def test_cosine_similarity_term_collision():
    """
    Test 4: Cosine-similarity term collision.
    """
    doc_freq = {
        "_total_chunks": 1000,
        "report": 800,
        "similarity": 20
    }
    assert idf_discount("report", doc_freq) < 0.2
    assert idf_discount("similarity", doc_freq) > 0.6
