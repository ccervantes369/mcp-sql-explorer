"""What the resources and prompts contain, and what they must never omit."""

import pytest

from mcp_server import (
    analyze_table,
    data_quality_report,
    schema_overview,
    table_schema,
)


def test_schema_overview_lists_every_table():
    text = schema_overview()

    assert "customers(" in text
    assert "orders(" in text


def test_schema_overview_marks_blocked_columns():
    # If this marker disappears, a caller plans a query that will be
    # refused, so it matters as much as the refusal itself.
    text = schema_overview()

    assert "email [blocked]" in text
    assert "phone [blocked]" in text


def test_schema_overview_leaves_readable_columns_unmarked():
    assert "city [blocked]" not in schema_overview()


def test_table_schema_describes_one_table():
    text = table_schema("customers")

    assert text.startswith("Table: customers")
    for column in ("id", "name", "city", "signup_date"):
        assert column in text


def test_table_schema_marks_blocked_columns():
    assert "email [blocked]" in table_schema("customers")


def test_table_schema_rejects_an_unknown_table():
    # The template accepts any address, so it leans on the same allowlist
    # describe_table uses.
    with pytest.raises(ValueError, match="Unknown table"):
        table_schema("customers; DROP TABLE orders")


def test_analyze_table_prompt_is_about_the_requested_table():
    text = analyze_table("orders")

    assert "orders" in text
    # A prompt is only useful if it points at the things it expects to be
    # used. If these names drift, the instructions stop matching the server.
    assert "run_query" in text
    assert "schema://orders" in text


def test_data_quality_report_prompt_gives_real_instructions():
    text = data_quality_report()

    assert len(text) > 100
    assert "duplicate" in text.lower()
