"""Proof that the safety guards on run_query actually hold."""

import pytest

from mcp_server import describe_table, list_tables, run_query


def test_lists_the_expected_tables():
    assert list_tables() == ["customers", "orders"]


def test_a_normal_query_returns_rows():
    result = run_query("SELECT name, city FROM customers LIMIT 3")

    assert result["row_count"] == 3
    assert result["truncated"] is False
    assert "name" in result["rows"][0]


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM orders",
        "UPDATE customers SET city = 'X'",
        "DROP TABLE orders",
        "INSERT INTO orders VALUES (99, 1, 'x', 1.0, '2026-01-01')",
    ],
)
def test_only_select_is_allowed(statement):
    with pytest.raises(ValueError, match="Only SELECT"):
        run_query(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT email FROM customers",
        "SELECT phone FROM customers",
        # SELECT * expands to include the blocked columns.
        "SELECT * FROM customers",
        # Filtering on a blocked column leaks it one guess at a time,
        # so this has to be refused too.
        "SELECT name FROM customers WHERE email LIKE '%ana%'",
    ],
)
def test_blocked_columns_are_refused(statement):
    with pytest.raises(ValueError, match="prohibited"):
        run_query(statement)


def test_a_large_result_is_truncated():
    # A three-way cross join of 40 rows is 64,000 rows.
    result = run_query("SELECT a.id FROM orders a, orders b, orders c")

    assert result["row_count"] == 500
    assert result["truncated"] is True


def test_an_unknown_table_is_rejected():
    with pytest.raises(ValueError, match="Unknown table"):
        describe_table("customers; DROP TABLE orders")


def test_a_slow_query_is_aborted():
    """The only slow test: it deliberately waits for the 5 second timeout."""
    # Four billion row combinations. Nothing finishes this in five seconds.
    statement = (
        "SELECT COUNT(*) FROM orders a, orders b, orders c, "
        "orders d, orders e, orders f"
    )
    with pytest.raises(ValueError, match="took longer than"):
        run_query(statement)
