import sqlite3
import json
import os
import threading
from datetime import datetime
from config import settings

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sentinel.db")

# Serialize all write operations to prevent SQLite "database is locked" errors
# across FastAPI request threads, the strategy loop thread, and the commerce poller thread.
_db_write_lock = threading.Lock()


def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
    except Exception:
        pass
    return conn


def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 1. Create trades table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            token_in TEXT NOT NULL,
            token_out TEXT NOT NULL,
            amount_in REAL NOT NULL,
            amount_out REAL NOT NULL,
            status TEXT NOT NULL,
            tx_hash TEXT NOT NULL,
            strategy TEXT NOT NULL,
            notes TEXT
        )
        """)

        # 2. Create commerce_jobs table (ERC-8183)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS commerce_jobs (
            id TEXT PRIMARY KEY,
            client TEXT NOT NULL,
            description TEXT NOT NULL,
            budget REAL NOT NULL,
            status TEXT NOT NULL,
            deliverable TEXT,
            created_at TEXT NOT NULL,
            settled_at TEXT
        )
        """)

        # 3. Create settings/state table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)

        # Insert default settings if not exists
        cursor.execute("SELECT 1 FROM agent_state WHERE key = 'strategy'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO agent_state (key, value) VALUES ('strategy', 'BALANCED')")
            cursor.execute("INSERT INTO agent_state (key, value) VALUES ('risk_guard', 'true')")
            cursor.execute("INSERT INTO agent_state (key, value) VALUES ('target_tokens', ?)",
                           (json.dumps(["BNB", "CAKE", "USDT"]),))

        conn.commit()
    finally:
        conn.close()


def log_trade(token_in: str, token_out: str, amount_in: float, amount_out: float, status: str, tx_hash: str, strategy: str, notes: str = ""):
    with _db_write_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO trades (timestamp, token_in, token_out, amount_in, amount_out, status, tx_hash, strategy, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.utcnow().isoformat() + "Z", token_in, token_out, amount_in, amount_out, status, tx_hash, strategy, notes))
            conn.commit()
        finally:
            conn.close()


def get_trades(limit: int = 50):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def insert_job(job_id: str, client: str, description: str, budget: float, status: str):
    with _db_write_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO commerce_jobs (id, client, description, budget, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (job_id, client, description, budget, status, datetime.utcnow().isoformat() + "Z"))
            conn.commit()
        finally:
            conn.close()


def update_job_status(job_id: str, status: str, deliverable: str = None, settled: bool = False):
    with _db_write_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            settled_at = datetime.utcnow().isoformat() + "Z" if settled else None

            if deliverable:
                cursor.execute("""
                UPDATE commerce_jobs 
                SET status = ?, deliverable = ?, settled_at = COALESCE(?, settled_at)
                WHERE id = ?
                """, (status, deliverable, settled_at, job_id))
            else:
                cursor.execute("""
                UPDATE commerce_jobs 
                SET status = ?, settled_at = COALESCE(?, settled_at)
                WHERE id = ?
                """, (status, settled_at, job_id))
            conn.commit()
        finally:
            conn.close()


def get_jobs(limit: int = 50):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM commerce_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_state(key: str, default: str = None):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM agent_state WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_state(key: str, value: str):
    with _db_write_lock:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO agent_state (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
        finally:
            conn.close()


# Initialize database tables on load
init_db()
