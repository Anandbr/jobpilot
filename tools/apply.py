"""
tools/apply.py

Browser automation for job applications.
Runs natively on Debian — no SSH/SCP needed.
OpenClaw controls Chrome directly on the same machine.

Flow:
1. Copy resume to OpenClaw media/inbound (local shutil.copy)
2. Navigate to LinkedIn job page
3. Detect Easy Apply vs external ATS
4. Fill form fields
5. Upload resume
6. Answer screening questions via Claude
7. Take screenshot and send to Telegram for review
8. Wait for user CONFIRM before submitting
"""

import subprocess
import time
import random
import re
import os
import shutil
import logging
from pathlib import Path
from dotenv import load_dotenv

from config.loader import get_candidate, get_candidate_for_user
from tools.notifier import send_message, send_photo, send_message_to
from tools.database import update_job_status

load_dotenv()

logger = logging.getLogger(__name__)

# OpenClaw media directory — where the browser expects upload files
MEDIA_INBOUND = Path(
    os.getenv(
        "OPENCLAW_MEDIA_PATH",
        "/home/anand/.openclaw/media/inbound"
    )
)

NOVNC_URL = os.getenv("NOVNC_URL", "http://10.0.0.164:6080/vnc_lite.html")

# ATS domains we recognise as real application portals
GOOD_DOMAINS = [
    "greenhouse", "lever", "ashby", "workday",
    "jobvite", "icims", "myworkday", "smartrecruiters",
    "rippling", "bamboohr"
]

# Domains to ignore when scanning new tabs for the real ATS URL
BAD_DOMAINS = [
    "li.protechts.net", "linkedin.com", "doubleclick.net",
    "google.com", "recaptcha.net", "accounts.google.com",
    "lnkd.demdex.net", "blob:"
]


# ============================================================
# BROWSER HELPER
# ============================================================

def browser(command: str) -> str:
    """
    Run an OpenClaw browser command directly on this machine.
    No SSH — JobPilot and OpenClaw are on the same Debian server.
    DISPLAY=:99 ensures OpenClaw uses the Xvfb virtual display.
    """
    result = subprocess.run(
        f"openclaw browser {command}",
        shell=True,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "DISPLAY": ":99"}
    )
    if result.returncode != 0 and result.stderr:
        logger.warning(
            f"[BROWSER] Command error | "
            f"cmd={command[:50]} | err={result.stderr[:100]}"
        )
    return result.stdout.strip()


def human_delay(min_sec: float = 1.5, max_sec: float = 4.0):
    """
    Random human-like delay between browser actions.
    Reduces bot detection risk by avoiding perfectly timed clicks.
    """
    time.sleep(random.uniform(min_sec, max_sec))


# ============================================================
# FILE HELPERS — local only, no SCP
# ============================================================

def copy_resume_to_media(local_pdf_path: str) -> str:
    """
    Copy tailored resume PDF to OpenClaw's media/inbound directory
    so the browser can upload it to job application forms.

    Returns the full path OpenClaw expects when uploading.

    Why shutil.copy and not SCP — JobPilot and OpenClaw are now
    on the same Debian machine. Local copy is instant and has
    no network dependency.
    """
    MEDIA_INBOUND.mkdir(parents=True, exist_ok=True)

    filename = Path(local_pdf_path).name
    dest_path = MEDIA_INBOUND / filename

    shutil.copy(local_pdf_path, dest_path)

    logger.info(f"[APPLY] Resume copied to media | file={filename}")
    return str(dest_path)


def take_screenshot_and_send(job_id: str, caption: str) -> bool:
    """
    Take a full-page screenshot and send to Telegram.
    Runs locally — finds the latest PNG in OpenClaw's media dir.
    """
    browser("screenshot --full-page")

    browser_media = Path("/home/anand/.openclaw/media/browser")
    screenshots = sorted(
        browser_media.glob("*.png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not screenshots:
        logger.warning(f"[APPLY] No screenshot found | job_id={job_id[:8]}")
        return False

    latest = screenshots[0]
    logger.info(f"[APPLY] Screenshot taken | file={latest.name}")

    return send_photo(str(latest), caption)


# ============================================================
# APPLY URL DETECTION
# ============================================================

def get_real_apply_url(linkedin_url: str) -> tuple:
    """
    Navigate to a LinkedIn job page and find the real apply URL.

    Returns tuple: (url, is_easy_apply, easy_apply_ref)
      - url: the real ATS URL, or LinkedIn URL if Easy Apply
      - is_easy_apply: True if this is a LinkedIn Easy Apply job
      - easy_apply_ref: the OpenClaw ref to click for Easy Apply
    """
    logger.info(f"[APPLY] Navigating to LinkedIn job...")

    browser(f"open {linkedin_url}")
    human_delay(5, 7)

    # Scroll to load job content below the fold
    browser("evaluate --fn 'window.scrollTo(0, 400)'")
    human_delay(2, 3)

    snapshot = browser("snapshot")

    # DEBUG — log apply-related elements only
    logger.debug("[APPLY] Apply-related links and buttons:")
    for line in snapshot.split("\n"):
        line_lower = line.lower()
        if ("button" in line_lower or "link" in line_lower) and "apply" in line_lower:
            logger.debug(f"  {line.strip()[:100]}")

    # Priority 1 — "Apply on company website" → external ATS
    for line in snapshot.split("\n"):
        line_lower = line.lower()
        if 'link' in line_lower and 'apply on company website' in line_lower:
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                ref = ref_match.group(1)
                logger.info(f"[APPLY] External apply button found: {ref}")
                browser(f"click {ref}")
                human_delay(4, 6)

                tabs = browser("tabs")

                # First pass — look for known ATS domains
                for tab_line in tabs.split("\n"):
                    tab_lower = tab_line.lower()
                    if any(bad in tab_lower for bad in BAD_DOMAINS):
                        continue
                    if any(good in tab_lower for good in GOOD_DOMAINS):
                        url_match = re.search(r'https?://[^\s\]]+', tab_line)
                        if url_match:
                            real_url = url_match.group(0)
                            logger.info(f"[APPLY] Known ATS URL: {real_url[:80]}")
                            return real_url, False, None

                # Second pass — any non-bad tab
                for tab_line in tabs.split("\n"):
                    tab_lower = tab_line.lower()
                    if any(bad in tab_lower for bad in BAD_DOMAINS):
                        continue
                    url_match = re.search(r'https?://[^\s\]]+', tab_line)
                    if url_match:
                        real_url = url_match.group(0)
                        logger.info(f"[APPLY] Unknown ATS URL: {real_url[:80]}")
                        return real_url, False, None

    # Priority 2 — "Easy Apply to this job" (exact string)
    for line in snapshot.split("\n"):
        line_lower = line.lower()
        if 'link' in line_lower and 'easy apply to this job' in line_lower:
            logger.info(f"[APPLY] Easy Apply link found")
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                return linkedin_url, True, ref_match.group(1)

    # Priority 3 — Generic Apply button (exact match only)
    for line in snapshot.split("\n"):
        line_lower = line.lower()
        stripped = line_lower.strip()
        if (stripped.startswith('- button "apply"') or
                stripped.startswith('- button "apply now"')):
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                ref = ref_match.group(1)
                logger.info(f"[APPLY] Apply button found: {ref}")
                browser(f"click {ref}")
                human_delay(4, 6)

                tabs = browser("tabs")
                for tab_line in tabs.split("\n"):
                    tab_lower = tab_line.lower()
                    if any(bad in tab_lower for bad in BAD_DOMAINS):
                        continue
                    if any(good in tab_lower for good in GOOD_DOMAINS):
                        url_match = re.search(r'https?://[^\s\]]+', tab_line)
                        if url_match:
                            return url_match.group(0), False, None

    logger.warning("[APPLY] No apply button found on page")
    return linkedin_url, False, None


# ============================================================
# STUCK DETECTION
# ============================================================

def detect_stuck(snapshot: str) -> dict:
    """
    Detect if the browser is in a state the agent can't handle.
    Returns {stuck: bool, type: str, message: str}

    Why patterns not keywords — "captcha" appears in page source
    for invisible reCAPTCHA even on normal pages. We check for
    phrases that explicitly tell the user they need to act.
    """
    snapshot_lower = snapshot.lower()

    if any(x in snapshot_lower for x in [
        "verify you are human",
        "i'm not a robot",
        "prove you're human",
        "complete the captcha"
    ]):
        return {
            "stuck": True,
            "type": "captcha",
            "message": "CAPTCHA detected — need you to solve it"
        }

    if any(x in snapshot_lower for x in [
        "create your account",
        "create an account",
        "sign up for free",
        "register for free"
    ]):
        return {
            "stuck": True,
            "type": "account_creation",
            "message": "Account creation required"
        }

    if any(x in snapshot_lower for x in [
        "verify your email",
        "check your inbox",
        "we sent a code",
        "enter the code we sent"
    ]):
        return {
            "stuck": True,
            "type": "email_verification",
            "message": "Email verification required"
        }

    if any(x in snapshot_lower for x in [
        "sign in to continue",
        "log in to continue",
        "please sign in"
    ]):
        return {
            "stuck": True,
            "type": "login",
            "message": "Login required"
        }

    return {"stuck": False}


def send_stuck_notification(job: dict, stuck_info: dict, chat_id: str = None):
    """
    Send Telegram notification with screenshot and noVNC link
    when agent is stuck and needs human help.
    """
    import requests

    # Screenshot first so user sees what's happening
    take_screenshot_and_send(
        job_id=job["id"],
        caption=f"🚧 Agent stuck — {stuck_info['message']}"
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    base_url = f"https://api.telegram.org/bot{token}"

    keyboard = {
        "inline_keyboard": [[
            {"text": "📱 Open Browser", "url": NOVNC_URL},
            {"text": "✅ CONTINUE", "callback_data": f"continue_{job['id']}"},
            {"text": "❌ SKIP", "callback_data": f"skip_{job['id']}"}
        ]]
    }

    requests.post(
        f"{base_url}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": (
                f"🚧 <b>Agent needs your help!</b>\n\n"
                f"<b>{job['title']}</b> at <b>{job['company']}</b>\n\n"
                f"Stuck at: {stuck_info['message']}\n\n"
                f"Open noVNC to complete this step:\n{NOVNC_URL}\n\n"
                f"Complete the step then tap CONTINUE."
            ),
            "parse_mode": "HTML",
            "reply_markup": keyboard
        },
        timeout=10
    )

    logger.info(
        f"[APPLY] Stuck notification sent | "
        f"job={job['title']} | type={stuck_info['type']}"
    )


# ============================================================
# FORM FILLING
# ============================================================

def fill_standard_fields(snapshot: str, candidate: dict,
                          resume_path: str):
    """
    Fill standard fields deterministically — no AI needed.
    Maps common field label patterns to candidate values.
    Claude is NOT called here — these are always the same answers.
    """
    field_map = {
        "your name": candidate.get("name", ""),
        "full name": candidate.get("name", ""),
        "first name": (
            candidate.get("name", "").split()[0]
            if candidate.get("name") else ""
        ),
        "last name": (
            " ".join(candidate.get("name", "").split()[1:])
            if candidate.get("name") else ""
        ),
        "email": candidate.get("email", ""),
        "phone": candidate.get("phone", ""),
        "linkedin": candidate.get("linkedin", ""),
        "github": candidate.get("github", ""),
        "website": candidate.get("github", ""),
        "location": candidate.get("location", ""),
        "city": (
            candidate.get("location", "").split(",")[0].strip()
            if candidate.get("location") else ""
        ),
    }

    lines = snapshot.split("\n")
    for line in lines:
        line_lower = line.lower()
        for field_name, value in field_map.items():
            if field_name in line_lower and "textbox" in line_lower and value:
                ref_match = re.search(r'\[ref=(e\d+)\]', line)
                if ref_match:
                    ref = ref_match.group(1)
                    logger.info(f"[APPLY] Filling field | {field_name} → {ref}")
                    browser(f'type {ref} "{value}"')
                    human_delay(1, 3)


def answer_screening_question(question: str, job: dict, user: dict = None) -> str:
    """
    Use Claude to answer a screening question honestly.
    Only called for open-ended questions that require judgment.
    Deterministic fields (name, email, etc.) never go through here.
    """
    from tools.claude_client import call_claude
    from harness.skill_loader import (
        load_candidate_context, 
        load_extended_expereince,
        load_candidate_context_for_user,
        load_extended_experience_for_user
    )

    if user:
        candidate_context = load_candidate_context_for_user(user)
        extended = load_extended_experience_for_user(user)
    else:
        candidate_context = load_candidate_context()
        extended = load_extended_expereince()

    prompt = f"""You are helping a job candidate answer a screening question honestly.

CANDIDATE CONTEXT:
{candidate_context}

EXTENDED EXPERIENCE:
{extended}

JOB:
{job['title']} at {job['company']}

SCREENING QUESTION:
{question}

Write a concise, honest answer (2-4 sentences max) based only on the candidate's real experience.
Do not fabricate anything. Be specific and genuine.
Return only the answer text, nothing else."""

    return call_claude(
        prompt=prompt,
        call_type="screening_answer",
        use_powerful_model=False
    )


# ============================================================
# LINKEDIN EASY APPLY
# ============================================================

def handle_linkedin_easy_apply(job: dict, resume_path: str, chat_id: str = None) -> bool:
    """
    LinkedIn Easy Apply uses shadow DOM — cannot be automated.
    Send the LinkedIn URL to the user for manual apply on mobile.
    """
    import requests

    job_id = job["id"]
    job_url = job.get("url", "")

    logger.info(
        f"[EASY APPLY] Sending LinkedIn URL for manual apply | "
        f"job={job['title']} | job_id={job_id[:8]}"
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    base_url = f"https://api.telegram.org/bot{token}"

    keyboard = {
        "inline_keyboard": [[
            {"text": "📱 Open on LinkedIn", "url": job_url},
        ], [
            {"text": "✅ Applied!", "callback_data": f"applied_{job_id}"},
            {"text": "❌ Skip", "callback_data": f"skip_{job_id}"}
        ]]
    }

    requests.post(
        f"{base_url}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": (
                f"📱 <b>Easy Apply — apply on LinkedIn</b>\n\n"
                f"<b>{job['title']}</b> at <b>{job['company']}</b>\n\n"
                f"Tap the button to open on LinkedIn and apply directly.\n"
                f"Tap <b>Applied!</b> when done."
            ),
            "parse_mode": "HTML",
            "reply_markup": keyboard
        },
        timeout=10
    )

    update_job_status(job_id, "pending_manual")
    return True


# ============================================================
# SUBMIT
# ============================================================

def submit_application(job_id: str) -> bool:
    """
    Click the submit button on the current open form.
    Only called AFTER the user taps CONFIRM SUBMIT in Telegram.
    Never called automatically.
    """
    logger.info(f"[SUBMIT] User confirmed — submitting | job_id={job_id[:8]}")

    snapshot = browser("snapshot")

    submit_patterns = [
        "submit application", "submit", "apply now", "send application"
    ]

    for line in snapshot.split("\n"):
        line_lower = line.lower()
        if "button" in line_lower and any(p in line_lower for p in submit_patterns):
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                ref = ref_match.group(1)
                logger.info(f"[SUBMIT] Clicking submit button | ref={ref}")
                human_delay(2, 4)
                browser(f"click {ref}")
                human_delay(3, 5)

                snapshot_after = browser("snapshot")

                success_signals = [
                    "application submitted", "thank you", "we received",
                    "successfully submitted", "application received"
                ]

                if any(signal in snapshot_after.lower()
                       for signal in success_signals):
                    take_screenshot_and_send(
                        job_id=job_id,
                        caption="✅ Application submitted successfully!"
                    )
                    logger.info(
                        f"[SUBMIT] Success confirmed | job_id={job_id[:8]}"
                    )
                    return True
                else:
                    take_screenshot_and_send(
                        job_id=job_id,
                        caption="⚠️ Submitted — please verify in screenshot"
                    )
                    return True

    logger.warning(f"[SUBMIT] Submit button not found | job_id={job_id[:8]}")
    send_message("❌ Could not find submit button — please submit manually")
    return False


# ============================================================
# MAIN APPLY FUNCTION
# ============================================================

def apply_to_job(job: dict, pdf_path: str,
                 user: dict = None,
                 chat_id: str = None) -> bool:
    """
    Main apply function. Orchestrates the full application flow.

    Args:
        job: job dict from DB
        pdf_path: path to tailored resume PDF
        user: user dict from DB — if None, uses owner profile
        chat_id: Telegram chat_id to send notifications to

    Steps:
    1. Copy resume to OpenClaw media directory (local)
    2. Find real apply URL from LinkedIn
    3. Navigate to application form
    4. Fill standard fields (deterministic)
    5. Upload resume
    6. Answer screening questions (Claude)
    7. Take screenshot and send to Telegram for review
    8. Send SUBMIT NOW / CANCEL buttons — wait for user

    Does NOT submit. User must tap SUBMIT NOW in Telegram.
    Returns True if form was filled and screenshot sent.
    """
    if user:
        candidate = get_candidate_for_user(user)
    else:
        candidate = get_candidate()
    
    # Use per user chat_id if available
    notify_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    job_id = job["id"]
    job_title = job.get("title", "Unknown")
    job_company = job.get("company", "Unknown")

    logger.info(
        f"[APPLY] Starting | job={job_title} at {job_company} | "
        f"job_id={job_id[:8]}"
    )
    send_message_to(notify_chat_id,
        f"🤖 Starting application for "
        f"<b>{job_title}</b> at <b>{job_company}</b>..."
    )

    try:
        # Step 1 — Copy resume to OpenClaw media (local, no SCP)
        logger.info(f"[APPLY] [{job_id[:8]}] Copying resume to media...")
        resume_path = copy_resume_to_media(pdf_path)
        human_delay(1, 2)

        # Step 2 — Find real apply URL
        logger.info(f"[APPLY] [{job_id[:8]}] Finding apply URL...")
        apply_url, is_easy_apply, easy_apply_ref = get_real_apply_url(
            job.get("url", "")
        )

        # Step 3 — Navigate to application
        if is_easy_apply:
            logger.info(
                f"[APPLY] [{job_id[:8]}] LinkedIn Easy Apply — "
                f"sending URL to user"
            )
            send_message_to(notify_chat_id, "📋 LinkedIn Easy Apply — sending link...")
            if easy_apply_ref:
                browser(f"click {easy_apply_ref}")
                human_delay(3, 5)
            return handle_linkedin_easy_apply(job, resume_path, notify_chat_id)

        logger.info(
            f"[APPLY] [{job_id[:8]}] External ATS: {apply_url[:80]}"
        )
        browser(f"open {apply_url}")
        human_delay(3, 5)

        # Step 4 — Get snapshot
        snapshot = browser("snapshot")

        # Step 5 — Stuck check
        stuck = detect_stuck(snapshot)
        if stuck["stuck"]:
            logger.warning(
                f"[APPLY] [{job_id[:8]}] Stuck | type={stuck['type']}"
            )
            send_stuck_notification(job, stuck, notify_chat_id)
            return False

        # Step 6 — Fill standard fields
        logger.info(f"[APPLY] [{job_id[:8]}] Filling standard fields...")
        fill_standard_fields(snapshot, candidate, resume_path)
        human_delay(2, 4)

        # Step 7 — Upload resume
        logger.info(f"[APPLY] [{job_id[:8]}] Uploading resume...")
        snapshot = browser("snapshot")
        upload_patterns = [
            "upload file", "resume/cv", "upload resume",
            "choose file", "attach resume"
        ]
        for line in snapshot.split("\n"):
            line_lower = line.lower()
            if (any(p in line_lower for p in upload_patterns)
                    and "button" in line_lower):
                ref_match = re.search(r'\[ref=(e\d+)\]', line)
                if ref_match:
                    ref = ref_match.group(1)
                    logger.info(
                        f"[APPLY] [{job_id[:8]}] Upload ref: {ref}"
                    )
                    browser(f"upload --input-ref {ref} {resume_path}")
                    human_delay(1, 2)
                    browser(f"click {ref}")
                    human_delay(2, 3)
                    break

        # Step 8 — Answer screening questions
        logger.info(
            f"[APPLY] [{job_id[:8]}] Checking for screening questions..."
        )
        snapshot = browser("snapshot")
        screening_patterns = [
            "in a few sentences", "describe", "tell us",
            "why do you", "how many years", "experience with"
        ]
        for line in snapshot.split("\n"):
            line_lower = line.lower()
            if ("textbox" in line_lower
                    and any(p in line_lower for p in screening_patterns)):
                ref_match = re.search(r'\[ref=(e\d+)\]', line)
                if ref_match:
                    ref = ref_match.group(1)
                    question = (
                        line.split('"')[1] if '"' in line
                        else "screening question"
                    )
                    logger.info(
                        f"[APPLY] [{job_id[:8]}] "
                        f"Answering: {question[:60]}..."
                    )
                    answer = answer_screening_question(question, job, user=user)
                    browser(f'type {ref} "{answer}"')
                    human_delay(3, 5)

        # Step 9 — Screenshot for review
        logger.info(
            f"[APPLY] [{job_id[:8]}] Taking screenshot for review..."
        )
        human_delay(2, 3)
        take_screenshot_and_send(
            job_id=job_id,
            caption=(
                f"📋 <b>Review before submitting</b>\n\n"
                f"<b>{job_title}</b> at <b>{job_company}</b>\n\n"
                f"Check all fields carefully.\n"
                f"Tap SUBMIT NOW to submit or CANCEL to abort."
            )
        )

        # Step 10 — Confirmation buttons (no auto-submit)
        from tools.notifier import send_apply_confirmation
        send_apply_confirmation(job)

        update_job_status(job_id, "ready_to_apply")
        logger.info(
            f"[APPLY] [{job_id[:8]}] Form ready — "
            f"waiting for user confirmation"
        )
        return True

    except Exception as e:
        logger.error(
            f"[APPLY] Failed | job={job_title} at {job_company} | "
            f"job_id={job_id[:8]} | error={e}"
        )
        send_message_to(notify_chat_id,
            f"❌ Apply failed for <b>{job_title}</b> "
            f"at <b>{job_company}</b>\nError: {e}"
        )
        return False