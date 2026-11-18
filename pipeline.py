import csv
import logging
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from time import perf_counter

DB_PATH = Path(__file__).with_name("pipeline.sqlite3")
SAMPLE_PATH = Path(__file__).with_name("sample_orders.csv")
MAX_BYTES = 5 * 1024 * 1024
FIELDS = ("order_id", "product", "amount")
logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    source TEXT NOT NULL,
    extract_status TEXT NOT NULL,
    transform_status TEXT NOT NULL,
    load_status TEXT NOT NULL,
    processed INTEGER,
    rejected INTEGER,
    loaded INTEGER,
    duration_ms REAL NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    run_id INTEGER NOT NULL REFERENCES pipeline_runs(id),
    order_id TEXT NOT NULL,
    product TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    PRIMARY KEY (run_id, order_id)
);
"""

Order = tuple[str, str, int]


def extract_orders(content: bytes) -> list[list[str]]:
    if len(content) > MAX_BYTES:
        raise ValueError("The CSV must be 5 MB or smaller.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Save the CSV with UTF-8 encoding and try again.") from error
    reader = csv.reader(StringIO(text, newline=""), strict=True)
    try:
        header = [field.strip().lower() for field in next(reader, [])]
        if sorted(header) != sorted(FIELDS):
            raise ValueError("Expected exactly these columns: order_id, product, amount.")
        rows = [row for row in reader if row]
    except csv.Error as error:
        raise ValueError(f"CSV parsing failed near line {reader.line_num}.") from error
    if not rows:
        raise ValueError("The CSV contains a header but no order rows.")
    positions = [header.index(field) for field in FIELDS]
    return [[row[index] for index in positions] if len(row) == len(FIELDS) else []
            for row in rows]


def transform_orders(rows: list[list[str]]) -> tuple[list[Order], Counter[str]]:
    orders: list[Order] = []
    seen: set[str] = set()
    rejections: Counter[str] = Counter()
    for row in rows:
        if not row:
            rejections["wrong number of columns"] += 1
            continue
        order_id, product, amount = (field.strip() for field in row)
        if not order_id or not product:
            rejections["missing order ID or product"] += 1
        elif not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", amount):
            rejections["invalid amount"] += 1
        elif order_id in seen:
            rejections["duplicate order ID"] += 1
        else:
            orders.append((order_id, product, int(Decimal(amount) * 100)))
            seen.add(order_id)
    return orders, rejections


def run_pipeline(content: bytes, source: str, db_path: Path = DB_PATH) -> int:
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    start = perf_counter()
    extract_status, transform_status, load_status = "Failed", "Skipped", "Skipped"
    processed = rejected = loaded = None
    orders: list[Order] = []
    try:
        rows = extract_orders(content)
    except ValueError as error:
        detail = str(error)
    else:
        extract_status, transform_status = "Succeeded", "Succeeded"
        processed = len(rows)
        orders, rejections = transform_orders(rows)
        rejected = sum(rejections.values())
        loaded = len(orders)
        detail = "All records loaded." if not rejected else "Rejected: " + "; ".join(
            f"{count} {reason}" for reason, count in sorted(rejections.items())
        ) + "."
        if orders:
            load_status = "Succeeded"
        else:
            detail = "No valid orders to load. " + detail

    def save_run(connection: sqlite3.Connection) -> int:
        cursor = connection.execute(
            """INSERT INTO pipeline_runs (
                started_at, source, extract_status, transform_status, load_status,
                processed, rejected, loaded, duration_ms, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (started_at, source, extract_status, transform_status, load_status,
             processed, rejected, loaded, round((perf_counter() - start) * 1000, 1),
             detail),
        )
        run_id = cursor.lastrowid
        if run_id is None:
            raise sqlite3.DatabaseError("Pipeline run ID was not recorded.")
        return run_id

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        try:
            with connection:
                run_id = save_run(connection)
                if orders:
                    connection.executemany(
                        """INSERT INTO orders (run_id, order_id, product, amount_cents)
                           VALUES (?, ?, ?, ?)""",
                        ((run_id, *order) for order in orders),
                    )
                    connection.execute(
                        "UPDATE pipeline_runs SET duration_ms = ? WHERE id = ?",
                        (round((perf_counter() - start) * 1000, 1), run_id),
                    )
            return run_id
        except sqlite3.Error:
            if not orders:
                raise
            logger.exception("Could not save pipeline orders and run log")
            load_status, loaded = "Failed", 0
            detail = "SQLite could not save the orders. No orders from this run were committed."
            with connection:
                return save_run(connection)


def read_runs(db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 50"
        ).fetchall()
