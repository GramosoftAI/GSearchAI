"""Unit tests for get_singular_plural_variants exception handling and morphology."""

import pytest
from app.modules.database_knowledgebase.knowledge.retrieval.table_retriever import (
    get_singular_plural_variants,
    DEFAULT_NON_STRIPPING_S_WORDS,
)


def test_variants_news():
    variants = get_singular_plural_variants("news")
    # Must not strip trailing "s" to form "new"
    assert "new" not in variants
    assert "news" in variants


def test_variants_status():
    variants = get_singular_plural_variants("status")
    # Must not strip trailing "s" to form non-word "statu"
    assert "statu" not in variants
    assert "status" in variants
    assert "statuses" in variants


def test_variants_users():
    variants = get_singular_plural_variants("users")
    assert "user" in variants
    assert "users" in variants


def test_variants_entries():
    variants = get_singular_plural_variants("entries")
    assert "entry" in variants
    assert "entries" in variants


def test_variants_projects():
    variants = get_singular_plural_variants("projects")
    assert "project" in variants
    assert "projects" in variants


def test_variants_meetings():
    variants = get_singular_plural_variants("meetings")
    assert "meeting" in variants
    assert "meetings" in variants


def test_other_exceptions():
    for word in ["series", "address", "access", "analysis", "bus"]:
        variants = get_singular_plural_variants(word)
        # Verify no illegal stem truncation
        if word == "series":
            assert "serie" not in variants
        elif word == "analysis":
            assert "analysi" not in variants
        elif word == "bus":
            assert "bu" not in variants
