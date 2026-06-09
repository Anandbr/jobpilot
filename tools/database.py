import sqlite3
import json
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"

def get_connection():
    """Get a database connection."""
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)

def initialze_database():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Jobs table - every job the agent finds
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
                   company TEXT NOT NULL,
                   location TEXT,
                   url TEXT,
                   jd_text TEXT,
                   posted_at TEXT,
                   discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   source TEXT,
                   score REAL,
                   score_reasoning TEXT,
                   stron_matches TEXT,
                   gaps TEXT,
                   status TEXT DEFAULT 'pending'
        )
    """)

    # Resumes table - tailored resume for each job
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resumes (
                   id TEXT PRIMARY KEY,
                   job_id TEXT NOT NULL,
                   tailored_text TEXT,
                   file_path TEXT,
                   created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   FOREIGN KEY (job_id) REFERENCES jobs (id)
        )
    """)

    #Applications table - tracking status of application
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS applications(
                   id TEXT PRIMARY KEY,
                   job_id TEXT NOT NULL,
                   resume_id TEXT,
                   applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
                   recruiter_name TEXT,
                   recruiter_url TEXT,
                   outreach_sent INTEGER DEFAULT 0,
                   response_type TEXT,
                   response_at TEXT,
                   FOREIGN KEY (job_id) REFERENCES jobs (id)
        )
    """)

    #API usage table - cost monitoring
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_usage (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   date TEXT NOT NULL,
                   tokens_used INTEGER DEFAULT 0,
                   cost_usd REAL DEFAULT 0.0,
                   call_type TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully")


# --------------------JOB FUNCTIONS---------------------------

def save_job(job: dict):
    """Save a new job to the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
            INSERT OR IGNORE INTO jobs
            (id, title, company, location, url, jd_text, posted_at, source)
            VALUES(?,?,?,?,?,?,?,?)
    """, (
        job["id"],
        job["title"],
        job["company"],
        job.get("locatino"),
        job.get("url"),
        job.get("jd_text"),
        job.get("posted_at"),
        job.get("source")
    ))
    conn.commit()
    conn.close()

def get_job(job_id: str) -> dict | None:
    """Get a job by ID."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def job_already_scored(job_id: str) -> bool:
    """Check if we already scored this job - avaids repeat API calls."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT score FROM jobs WHERE id = ? AND score is NOT NULL", (job_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_score(job_id: str, score: float, reasoning: str,
               strong_matches: list, gaps: list):
    """Save scoring results for a job."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE jobs
        SET score = ?, score_reasoning = ?, stron_matches = ?, gaps = ? WHERE id = ?
    """, (
        score,
        reasoning,
        json.dumps(strong_matches),
        json.dumps(gaps),
        job_id
    ))
    conn.commit()
    conn.close()

def get_pending_jobs() -> list:
    """Get all jobs not yet reviewed by user."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM jobs
        WHERE status = 'pending' AND score >= 7.0
        ORDER BY score DESC
        """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_job_status(job_id: str, status: str):
    """Update job status - applied, skipped, interview, rejected."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""UPDATE jobs SET status = ? WHERE id = ?""", (status, job_id))
    conn.commit()
    conn.close()

# --------------------API USAGE FUNCTIONS---------------------------

def log_api_call(tokens: int, cost: float, call_type: str):
    """Log every Claude API call for cost monitoring."""
    from datetime import date as date_class
    today = date_class.today().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO api_usage (date, tokens_used, cost_usd, call_type)
        VALUES (?, ?, ?, ?)
    """, (today, tokens, cost, call_type))
    conn.commit()
    conn.close()

def get_api_spend_today() -> float:
    """Get total API spend today - for budget enforcement."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(""" 
        SELECT COALESCE(SUM(cost_usd), 0)
                   FROM api_usage
                   WHERE date = ?
                   """, (date.today().isoformat(),))
    result = cursor.fetchone()[0]
    conn.close()
    return result


# --------------------RESUME FUNCTIONS---------------------------

def save_resume(job_id: str, tailored_text: str, file_path: str):
    """Save a tailored resume for a job."""
    import uuid
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO resumes (id, job_id, tailored_text, file_path)
        VALUES(?,?,?,?)
        """, (str(uuid.uuid4()), job_id, tailored_text, file_path))
    conn.commit()
    conn.close()

def get_resume_for_job(job_id: str) -> dict | None:
    """Get tailored resume for a job if it exists."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resumes WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# --------------------INITIALIZE ON IMPORT---------------------------
initialze_database()