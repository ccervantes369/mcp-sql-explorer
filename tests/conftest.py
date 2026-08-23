"""Shared setup that pytest loads automatically before any test runs."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session", autouse=True)
def sample_database():
    """Build sample.db if it is missing.

    The database is gitignored, so a fresh clone will not have one. This
    lets the test suite run straight after cloning, with no manual step.
    """
    if not (ROOT / "sample.db").exists():
        import make_sample_db

        make_sample_db.main()
