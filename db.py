import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "underwriter.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            hashed_password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'lender_reviewer',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            metrics_json TEXT NOT NULL,
            report_filename TEXT NOT NULL,
            consent_given INTEGER NOT NULL DEFAULT 0,
            consent_text TEXT,
            consent_timestamp TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lender_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            lender_id INTEGER NOT NULL,
            accessed_at TEXT NOT NULL DEFAULT (datetime('now')),
            ip_address TEXT,
            FOREIGN KEY (submission_id) REFERENCES submissions(id),
            FOREIGN KEY (lender_id) REFERENCES lenders(id)
        );

        CREATE INDEX IF NOT EXISTS idx_submissions_token ON submissions(token);
        CREATE INDEX IF NOT EXISTS idx_lender_access_submission ON lender_access(submission_id);
    """)
    conn.commit()
    conn.close()