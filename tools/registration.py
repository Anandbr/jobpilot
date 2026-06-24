"""
Registration state machine for JobPilot multi-user onboarding.

State machine - stpres which registration step each user in on, 
and defines valid transitions between steps. DB_backed so server
restarts don't lose progress.

Steps in order:
name -> email -> phone -> location -> linkedin -> github -> visa_status
-> salary -> base_resume -> complete

Each step:
1. Bot sends a question
2. User replies
3. Validate the output
4. Save to users table
5. Advance to next step
"""

import uuid
import logging
import time
from prometheus_client import Counter, Histogram
from tools.database import (
    get_connection, get_job_preferences, save_job_preferences
)

logger = logging.getLogger(__name__)

# ============================================================
# METRICS — defined here, close to the code they measure
# ============================================================

registration_started = Counter(
    'jobpilot_registration_started_total',
    'Number of users who triggered registration'
)

registration_completed = Counter(
    'jobpilot_registration_completed_total',
    'Number of users who completed registration'
)

registration_abondoned = Counter(
    'jobpilot_registation_abandoned_total',
    'Registration abonded, by step',
    ['step']
)

registration_step_duration = Histogram(
    'jobpilot_registration_step_duration_seconds',
    'Time between user messages per step',
    ['step'],
    buckets=[5, 15, 30, 60, 120, 300, 600]
)

# ============================================================
# STEP DEFINITIONS
# The order of this list IS the state machine's transition map.
# Each step has:
# - key: the DB column we're filling
# - question: what the bot asks the user
# - required: whether user can skip this step
# ============================================================

REGISTRATION_STEPS = [
    {
        "key": "name",
        "question": (
            "👋 Welcome to JobPilot!\n\n"
            "I'll help you find and apply to jobs automatically.\n\n"
            "Let's get you set up. What's your full legal name?"
        ),
        "required": True
    },
    {
        "key": "email",
        "question": "what email address should I use on job application?",
        "required": True
    },
    {
        "key": "phone",
        "question": "what's your phone unmber? (include country code, eg, +1 206 523 1234)",
        "required": True
    },
    {
        "key": "location",
        "question": "what city are you based in? (e.g, Seattle, WA)",
        "required": True
    },
    {
        "key": "linkedin_url",
        "question": "What's your linkedin profile URL?",
        "required": True
    },
    {
        "key": "github_url",
        "question": (
            "What's your GitHub profile URL?\n\n"
            "Don't have one? Reply /skip"
        ),
        "required": False
    },
    {
        "key": "visa_status",
        "question": (
        "What's your work authorization status in the country "
        "you're looking for work in?\n\n"
        "Be specific — e.g. 'US citizen', 'H1B transfer needed', "
        "'UK Graduate visa', 'EU citizen', 'Need sponsorship'\n\n"
        "This helps me answer work authorization questions on "
        "applications accurately."
        ),
        "required": True
    },
    {
        "key": "salary_expectation",
        "question": (
        "What's your salary expectation?\n\n"
        "Include currency and range "
        "(e.g. 150k-200k USD, 80k-100k GBP, 25-35 LPA)\n\n"
        "Don't want to share? Reply /skip"
        ),
        "required": False
    },
    {
        "key": "base_resume",
        "question": (
            "Last step - please upload your base resume as a PDF.\n\n"
            "This is the foundation I'll use to tailor your resumes for each role."
        ),
        "required": True
    },
    {
        "key": "job_titles",
        "question": (
            "Almost done! What job titles are you targeting?\n\n"
            "Send them separated by commas:\n"
            "e.g. AI Engineer, ML Engineer, Software Engineer\n\n"
            "I'll search LinkedIn for these roles daily."
        ),
        "required": True
    },
    {
        "key": "job_locations",
        "question": (
            "Which locations are you open to?\n\n"
            "Send them separated by commas:\n"
            "e.g. Remote, Seattle, San Francisco, New York\n\n"
            "Include 'Remote' if you're open to remote roles."
        ),
        "required": True
    },
]

# Build a flat ordered list of step keys for easy navigation
STEP_KEYS = [s["key"] for s in REGISTRATION_STEPS]

# Maps step key → DB column name, only when they differ.
# Steps not listed here use the key name directly as the column.
STEP_KEY_TO_COLUMN = {
    "base_resume": "base_resume",
    # job pref steps handled separately — not in users table
    "job_titles": None,
    "job_locations": None,
}

# ============================================================
# DATABASE HELPERS
# ============================================================
def get_user_by_chat_id(chat_id: str) -> dict | None:
    """
    Look up a use by their Telegram chat ID.
    Returns a dict of all user fields, or None if not found.
    """
    conn = get_connection()
    conn.row_factory = __import__('sqlite3').Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM users WHERE telegram_chat_id = ?",
        (str(chat_id),)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(chat_id: str) -> dict:
    """Create a new user record when we see a chat_id for the first time.
    Sets registration_status='in_progress' and registration_step='name.
    Return the newly created user dict.
    """
    import os

    #Check user cap
    max_users = int(os.getenv("MAX_USERS", "50"))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    conn.close()

    if total >= max_users:
        logger.warning(
            f"[REGISTRATION] User cap reached | "
            f"total={total} | max={max_users} | chat_id={chat_id}"
        )
        return None
    
    user_id = str(uuid.uuid4())
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (
                id, telegram_chat_id, registration_status,
                registration_step, created_at, updated_at
            ) VALUES (?, ?, 'in_progress', 'name',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) 
        """, (user_id, str(chat_id)))
        conn.commit()
    except Exception as e:
        # UNIQUE constraint violation — chat_id already exists
        logger.warning(
            f"[REGISTRATION] Duplicate chat_id | chat_id={chat_id}"
        )
    conn.close()

    logger.info(f" [REGISTRATION] New user created | chat_id={chat_id} | user_id={user_id}")
    registration_started.inc()

    return get_user_by_chat_id(chat_id)

# Steps that save to job_preferences, not users table
JOB_PREF_STEPS = {"job_titles", "job_locations"}

def save_registration_field(chat_id: str, field: str, value:str):
    """
    Save a single field from registration and advance to next step.
    Most fields go to users table.
    job_titles and job_locations go to job_preferences table.
    Also records how long this step took (for metrics).
    """
    # Get current user to find timing info
    user = get_user_by_chat_id(chat_id)
    if not user:
        logger.error(f"[REGISTRATION] save_registration_field called for unknown chat_id={chat_id}")
        return

    # Record step duration if we have a timestamp to compare
    if user.get("updated_at"):
        try:
            # SQLite stores timestamps as strings — parse them
            from datetime import datetime
            last_update = datetime.fromisoformat(user["updated_at"])
            duration = (datetime.utcnow() - last_update).total_seconds()
            registration_step_duration.labels(step=field).observe(duration)
        except Exception as e:
            logger.warning(f"[REGISTRATION] Could not record step duration: {e}")

    # Determine next step
    if field in STEP_KEYS:
        current_index = STEP_KEYS.index(field)
        if current_index + 1 < len(STEP_KEYS):
            next_step = STEP_KEYS[current_index + 1]
            new_status = "in_progress"
        else:
            next_step = "complete"
            new_status = "complete"
    else:
        logger.error(f"[REGISTRATION] Unknown field: {field}")
        return
    
    # Job preference steps -> job_preferences table
    if field in JOB_PREF_STEPS:
        prefs = get_job_preferences(user["id"])

        if field == "job_titles":
            #Parse comma-seperated titles into a list
            titles = [t.strip() for t in value.split(",") if t.strip()]
            # Auto generated role_keywords from titles
            keywords = [t.lower() for t in titles]
            prefs["target_roles"] = titles
            prefs["role_keywords"] = keywords
        
        elif field == "job_locations":
            locations = [l.strip() for l in value.split(",") if l.strip()]
            prefs["locations"] = locations
        
        save_job_preferences(user["id"], prefs)

        #Infer h1b sponsorships from visa status
        visa = user.get("visa_status", "").lower()
        if "h1b" in visa or "sponsorship" in visa:
            prefs["h1b_sponsorship_required"] = True
            save_job_preferences(user["id"], prefs)
        
        # Still advance registration_step in users table
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users
            SET registration_step = ?,
                registration_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_chat_id = ?
        """, (next_step, new_status, str(chat_id)))
        conn.commit()
        conn.close()

    #All other steps
    else:
        db_column = STEP_KEY_TO_COLUMN.get(field, field)    

        # Safety guard — should never happen if JOB_PREF_STEPS
        # is handled correctly above
        if db_column is None:
            logger.error(
                f"[REGISTRATION] db_column is None for field={field} "
                f"— this step should have been caught earlier"
            )
            return
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE users 
            SET {db_column} = ?,
                registration_step = ?,
                registration_status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_chat_id = ?
        """, (value, next_step, new_status, str(chat_id)))
        conn.commit()
        conn.close()

    logger.info(
        f"[REGISTRATION] Step saved | chat_id={chat_id} | "
        f"field={field} | next_step={next_step}"
    )

    if new_status == "complete":
        registration_completed.inc()
        logger.info(f"[REGISTRATION] Registration complete | chat_id={chat_id}")

def save_resume_path(chat_id: str, file_path: str):
    """
    Specifically for the base_resume step — saves the path 
    to the uploaded PDF, then marks registration complete.
    """
    save_registration_field(chat_id, "base_resume", file_path)


def is_registered(chat_id: str) -> bool:
    """
    Returns True if this user has completed registration.
    Use this as the gate in notifier.py before any job-related action.
    """
    user = get_user_by_chat_id(chat_id)
    if not user:
        return False
    return user.get("registration_status") == "complete"

# ============================================================
# QUESTION HELPERS
# ============================================================
def get_question_for_step(step: str) -> str:
    """
    Given a step key, return the question the both should ask.
    Returns None if step is 'complete' or unknown.
    """
    for s in REGISTRATION_STEPS:
        if s["key"] == step:
            return s["question"]
    return None

def step_is_required(step: str) -> bool:
    """Return whether a step can be skipped with /skip."""
    for s in REGISTRATION_STEPS:
        if s["key"] == step:
            return s["required"]
    return True


# ============================================================
# MAIN HANDLER — called from notifier.py on every message
# ============================================================
def handle_registration_message(chat_id: str, text: str, document=None) -> str:
    """
    The core state machine holder. Called from notifier.py whenever a message
    for registration.

    Args:
    chat_id: Telegram chat ID (sting)
    text: message text (or None if document was sent)
    document: Telegram document object if user sent a file

    Returns:
    A string - The bot's reply to send back to the user.

    How it works:
    1. Look up user's current step
    2. Validate teh input for that step
    3. Save the value
    4. Return the next question (or completion message)
    """

    user = get_user_by_chat_id(chat_id)

    #Brand new user - create them and send forst question
    if not user:
        user = create_user(chat_id)
        if not user:
            return (
            "⚠️ JobPilot is currently at capacity.\n\n"
            "We're not accepting new registrations right now. "
            "Check back soon!"
        )
        first_question = get_question_for_step("name")
        return first_question
    
#Already complete - shouldn't be here. but handle gracefully
    if user.get("registration_status") == "complete":
        return None  # caller handles routing to main flow
    
    current_step = user.get("registration_step", "name")
    is_required = step_is_required(current_step)

    #Handle /skip for optional steps
    if text and text.strip().lower() == "/skip":
        if not is_required:
            logger.info(
                f"[REGISTRATION] Step skipped | "
                f"chat_id={chat_id} | step={current_step}"
            )
            save_registration_field(chat_id, current_step, "")
            # Re-fetch to get updated step
            updated_user = get_user_by_chat_id(chat_id)
            next_step = updated_user.get("registration_step")

            if next_step == "complete":
                return _completion_message()
            
            return get_question_for_step(next_step)
        else:
            return f"This step is required - I need your {current_step.replace('_', ' ')} to apply for jobs on your behalf."
    
    #Handle resume upload step (expects a PDF document)
    if current_step == "base_resume":
        if document:
            file_id = document.get("file_id", "")

            #Download PDF from Telegram to disk
            #Store real path. not file_id
            from tools.notifier import download_telegram_file

            user = get_user_by_chat_id(chat_id)
            user_id = user["id"] if user else chat_id

            #Save to data/resumes/{user_id}/base_resume.pdf
            save_path = f"data/resumes/{user_id}/base_resume.pdf"

            downloaded = download_telegram_file(file_id, save_path)
            if downloaded:
                save_resume_path(chat_id, save_path)
                logger.info(
                    f"[REGISTRATION] Resume downloaded | "
                    f"chat_id={chat_id} | path={save_path}"
                )
            else:
                logger.warning(
                    f"[REGISTRATION] Resume download failed, "
                    f"string file_id | chat_id={chat_id}"
                )
                return (
                    "⚠️ I received your resume but had trouble saving it. "
                    "Please try uploading again."
                )
            
            #Advance to next step
            updated_user = get_user_by_chat_id(chat_id)
            next_step = updated_user.get("registration_step")
            if next_step == "complete":
                return _completion_message()
            return get_question_for_step(next_step)
        else:
            return(
                "Please send your resume as a PDF file — "
                "tap the 📎 attachment button in Telegram."
            )            

    #All other steps expects text
    if not text or not text.strip():
        return "I didn't get that - could you try again?"
    
    value = text.strip()

    #Basic validation per step
    validation_error = _validate_step(current_step, value)
    if validation_error:
        return validation_error
    
    #Save and advance
    save_registration_field(chat_id, current_step, value)

    #Re-fetch to get the updated step
    updated_user = get_user_by_chat_id(chat_id)
    next_step = updated_user.get("registration_step")

    if next_step == "complete":
        return _completion_message()
    
    return get_question_for_step(next_step)


def _validate_step(step: str, value: str) -> str | None:
    """
    Basic validation for each step.
    Returns an error message string if invalid, None if valid.

    Why validate here and not in the DB? — the DB enforces 
    structure (NOT NULL, types), but business rules like 
    "email must contain @" are application logic, not DB logic.
    """
    if step == "email":
        if "@" not in value or "." not in value:
            return "That doesn't look like a valid email — please try again."

    if step == "linkedin_url":
        if "linkedin.com" not in value.lower():
            return "Please enter your full LinkedIn URL (e.g. https://linkedin.com/in/yourname)"

    if step == "github_url":
        if value and "github.com" not in value.lower():
            return "Please enter your full GitHub URL (e.g. https://github.com/yourusername) or /skip"

    if step == "phone":
        digits = ''.join(c for c in value if c.isdigit())
        if len(digits) < 10:
            return "Please enter a valid phone number with at least 10 digits."

    return None  # valid

def _completion_message() -> str:
    """The message sent when registration is fully complete."""
    return (
        "✅ You're all set!\n\n"
        "I'll start watching for matching jobs based on your profile.\n\n"
        "A few things you can do:\n"
        "• /experience-update — add more context about your work\n"
        "• /set-api-key — bring your own Claude API key for unlimited use\n"
        "• /profile — see what I have on file\n\n"
        "I'll notify you when I find strong matches. Good luck! 🚀"
    )
