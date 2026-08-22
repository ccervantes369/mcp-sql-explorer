"""Build a small SQLite database to develop against.

Run:  uv run python scripts/make_sample_db.py
It always rebuilds sample.db from scratch, so it is safe to re-run.
"""

import random
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "sample.db"

NAMES = [
    "Ana Ruiz", "Marc Oliver", "Lucia Fenn", "Tom Ridley", "Nadia Kerr",
    "Piotr Salk", "Elena Vasq", "Sam Achebe", "Rita Lindqvist", "Owen Blake",
    "Yuki Tanabe", "Farid Nasser", "Clara Bosch", "Ines Moreau", "Dev Rao",
]
CITIES = ["Madrid", "Lisbon", "Berlin", "Dublin", "Lyon", "Porto"]
PRODUCTS = ["Keyboard", "Monitor", "Desk lamp", "Chair", "Cable kit", "Headset"]


def main() -> None:
    random.seed(42)  # fixed seed: same data every time
    DB_PATH.unlink(missing_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE customers (
            id          INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL,
            phone       TEXT NOT NULL,
            city        TEXT NOT NULL,
            signup_date TEXT NOT NULL
        );
        CREATE TABLE orders (
            id          INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            product     TEXT NOT NULL,
            amount      REAL NOT NULL,
            order_date  TEXT NOT NULL
        );
    """)

    for i, name in enumerate(NAMES, start=1):
        handle = name.lower().replace(" ", ".")
        conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)",
            (
                i,
                name,
                f"{handle}@example.com",
                f"+34 6{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(100, 999)}",
                random.choice(CITIES),
                f"2025-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
            ),
        )

    for j in range(1, 41):
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
            (
                j,
                random.randint(1, len(NAMES)),
                random.choice(PRODUCTS),
                round(random.uniform(9.5, 480.0), 2),
                f"2026-{random.randint(1, 8):02d}-{random.randint(1, 28):02d}",
            ),
        )

    conn.commit()
    conn.close()
    print(f"Built {DB_PATH}")


if __name__ == "__main__":
    main()
