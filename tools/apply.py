import subprocess
import time
import random
import os
from pathlib import Path
from config.loader import get_candidate
from tools.notifier import send_message, send_photo
from tools.database import update_job_status
import re
from dotenv import load_dotenv

load_dotenv()

DEBIAN_HOST = os.getenv("DEBIAN_HOST")
DEBIAN_MEDIA_PATH = os.getenv("DEBIAN_MEDIA_PATH")
NOVNC_URL = os.getenv("NOVNC_URL")
SSH_KEY = os.getenv("DEBIAN_SSH_KEY")

def browser(command: str) -> str:
    """Run an OpenClaw browser command on Debian server."""
    result = subprocess.run(
        f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {DEBIAN_HOST} 'openclaw browser {command}'",
        shell=True,
        capture_output=True,
        text=True,
        timeout=60
    )
    return result.stdout.strip()

def scp_to_debian(local_path: str, remote_path: str):
    """Copy file to Debian via SCP using SSH key."""
    result = subprocess.run(
        f"scp -i {SSH_KEY} -o StrictHostKeyChecking=no "
        f"{local_path} {DEBIAN_HOST}:{remote_path}",
        shell=True,
        capture_output=True,
        text=True,
        timeout=60
    )
    if result.returncode != 0:
        raise Exception(f"SCP failed: {result.stderr}")
    
def scp_from_debian(remote_path: str, local_path: str):
    """Copy file from Debian via SCP using SSH key."""
    result = subprocess.run(
        f"scp -i {SSH_KEY} -o StrictHostKeyChecking=no "
        f"{DEBIAN_HOST}:{remote_path} {local_path}",
        shell=True,
        capture_output=True,
        text=True,
        timeout=60
    )
    if result.returncode != 0:
        raise Exception(f"SCP from Debian failed: {result.stderr}")

def human_delay(min_sec: float = 1.5, max_sec: float = 4.0):
    """Random human-like delay between actions."""
    time.sleep(random.uniform(min_sec, max_sec))

def copy_resume_to_debian(local_pdf_path: str)-> str:
    """
    Copy tailored resume PDF to Debian OpenClaw media folder.
    Returns the remote path.
    """
    filename = Path(local_pdf_path).name
    remote_path = f"{DEBIAN_MEDIA_PATH}/{filename}"
    scp_to_debian(local_pdf_path, remote_path)
    print(f"  [SCP] Resume copied to Debian: {filename}")
    return f"/home/anand/.openclaw/media/inbound/{filename}"

def take_screenshot_and_send(job_id: str, caption: str) -> bool:
    """Take screenshot on Debian and send to Telegram."""
    from tools.notifier import send_photo

    browser("screenshot --full-page")

    # Get latest screenshot path from Debian
    result = subprocess.run(
        f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no "
        f"{DEBIAN_HOST} 'ls -t ~/.openclaw/media/browser/*.png | head -1'",
        shell=True, capture_output=True, text=True, timeout=30
    )
    remote_path = result.stdout.strip()

    if not remote_path:
        print(f"  [SCREENSHOT] No screenshot found")
        return False

    # Copy to Mac with job_id in name
    local_path = f"/tmp/jobpilot_{job_id[:8]}.png"
    scp_from_debian(remote_path, local_path)

    return send_photo(local_path, caption)

def get_real_apply_url(linkedin_url: str) -> str:
    """
    Navigate to LinkedIn job page.
    Handles both Easy Apply and external Apply buttons.
    Returns tuple: (url, is_easy_apply)
    """
    print(f"  [APPLY] Navigating to LinkedIn job...")

    browser(f"open {linkedin_url}")
    human_delay(5, 7)

    # Scroll down to load job content
    browser("evaluate --fn 'window.scrollTo(0, 400)'")
    human_delay(2, 3)

    snapshot = browser("snapshot")

    # DEBUG — print all buttons found
    print("  [DEBUG] Links and buttons found:")
    for line in snapshot.split("\n"):
        line_lower = line.lower()
        if ("button" in line_lower or "link" in line_lower) and "apply" in line_lower:
            print(f"    {line.strip()[:100]}")
    # Check for Easy Apply link OR button
    # Check both links and buttons
    for line in snapshot.split("\n"):
        line_lower = line.lower()

        # Easy Apply link (LinkedIn logged in)
        if 'link' in line_lower and 'easy apply' in line_lower:
            print(f"  [APPLY] Found Easy Apply link: {line.strip()[:80]}")
            # Try direct URL first
            url_match = re.search(r'/url:\s*(https?://[^\s]+)', line)
            if url_match:
                easy_url = url_match.group(1)
                return easy_url, True, None
            # Fallback to ref click
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                return linkedin_url, True, ref_match.group(1)

        # Apply button
        if 'button' in line_lower and any(x in line_lower for x in [
            '"apply"', '"easy apply"', '"apply now"', '"apply for this job"'
        ]):
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                print(f"  [APPLY] Found Apply button: {line.strip()[:80]}")
                return linkedin_url, True, ref_match.group(1)

    # Look for external Apply button
    for line in snapshot.split("\n"):
        line_lower = line.lower()
        if 'button' in line_lower and line_lower.strip().startswith('- button "apply"'):
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                ref = ref_match.group(1)
                print(f"  [APPLY] External Apply at {ref} — clicking...")
                browser(f"click {ref}")
                human_delay(4, 6)

                # Find real ATS URL in new tabs
                bad_domains = [
                    "li.protechts.net", "linkedin.com", "doubleclick.net",
                    "google.com", "recaptcha.net", "accounts.google.com",
                    "lnkd.demdex.net", "blob:"
                ]
                good_domains = [
                    "greenhouse", "lever", "ashby", "workday",
                    "jobvite", "icims", "myworkday", "smartrecruiters",
                    "rippling", "bamboohr"
                ]

                tabs = browser("tabs")
                for tab_line in tabs.split("\n"):
                    tab_lower = tab_line.lower()
                    if any(bad in tab_lower for bad in bad_domains):
                        continue
                    if any(good in tab_lower for good in good_domains):
                        url_match = re.search(r'https?://[^\s\]]+', tab_line)
                        if url_match:
                            return url_match.group(0), False, None

    print(f"  [APPLY] No apply button found")
    return linkedin_url, False, None

def detect_stuck(snapshot: str) -> dict:
    """
    Detect if browser is stuck and needs human help.
    Returns stuck type and suggested action.
    """
    snapshot_lower = snapshot.lower()

    if any(x in snapshot_lower for x in ["captcha", "verify you are human", "robot"]):
        return {"stuck": True, "type": "captcha",
                "message": "CAPTCHA detected — need you to solve it"}

    if any(x in snapshot_lower for x in ["create account", "sign up", "register", "create your account"]):
        return {"stuck": True, "type": "account_creation",
                "message": "Account creation required"}

    if any(x in snapshot_lower for x in ["verify your email", "check your inbox", "confirmation code", "verification code"]):
        return {"stuck": True, "type": "email_verification",
                "message": "Email verification required"}

    if any(x in snapshot_lower for x in ["sign in", "log in", "login"]):
        return {"stuck": True, "type": "login",
                "message": "Login required"}

    return {"stuck": False}

def send_stuck_notification(job: dict, stuck_info: dict):
    """Send Telegram notification when agent is stuck."""
    import requests
    from tools.notifier import BASE_URL, TELEGRAM_CHAT_ID

    message = (
        f"🚧 <b>Agent needs your help!</b>\n\n"
        f"<b>{job['title']}</b> at <b>{job['company']}</b>\n\n"
        f"Stuck at: {stuck_info['message']}\n\n"
        f"👆 Open noVNC to complete this step:\n"
        f"{NOVNC_URL}\n\n"
        f"Complete the step then tap CONTINUE"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "📱 Open Browser", "url": NOVNC_URL},
            {"text": "✅ CONTINUE", "callback_data": f"continue_{job['id']}"},
            {"text": "❌ SKIP", "callback_data": f"skip_{job['id']}"}
        ]]
    }

    keyboard = {
        "inline_keyboard": [[
            {"text": "📱 Open Browser", "url": NOVNC_URL},
            {"text": "✅ CONTINUE", "callback_data": f"continue_{job['id']}"},
            {"text": "❌ SKIP", "callback_data": f"skip_{job['id']}"}
        ]]
    }

def fill_standard_fields(snapshot: str, candidate: dict, resume_remote_path: str):
    """
    Fill standard fields that are always the same.
    Deterministic - no AI needed.
    """
    #Common field patterns across ATS systems
    field_map = {
        "your name": candidate.get("name", ""),
        "full name": candidate.get("name", ""),
        "first name": candidate.get("name", "").split()[0] if candidate.get("name") else "",
        "last name": " ".join(candidate.get("name", "").split()[1:]) if candidate.get("name") else "",
        "email": candidate.get("email", ""),
        "phone": candidate.get("phone", ""),
        "linkedin": candidate.get("linkedin", ""),
        "github": candidate.get("github", ""),
        "website": candidate.get("github", ""),
        "location": candidate.get("location", ""),
        "city": candidate.get("location", "").split(",")[0].strip() if candidate.get("location") else "",
    }

    #Parse snapshot to find textbook refs
    lines = snapshot.split("\n")
    for i, line in enumerate(lines):
        line_lower = line.lower()

        for field_name, value in field_map.items():
            if field_name in line_lower and "textbok" in line_lower:
                #Extract ref
                import re
                ref_match = re.search(r'\[ref=(e\d+)\]', line)
                if ref_match:
                    ref = ref_match.group(1)
                    print(f" [FILL] {field_name} -> {ref}")
                    browser(f'type {ref} "{value}"')
                    human_delay(1,3)


def answer_screening_question(question: str, job:dict) -> str:
    """
    Use Claude to answer a screening question honestly.
    TODO: Need to make sure this doesn't completely answer the question.
    """
    from tools.claude_client import call_claude
    from harness.skill_loader import load_candidate_context, load_extended_experience

    candidate_context = load_candidate_context()
    extended = load_extended_experience()

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

def submit_application(job_id: str) -> bool:
    """
    Actually click the submit button.
    Only called after user taps CONFIRM in Telegram.
    """
    print(f"  [SUBMIT] User confirmed — submitting {job_id[:8]}...")

    # Take fresh snapshot to get current refs
    snapshot = browser("snapshot")

    import re

    # Find submit button
    submit_patterns = ["submit application", "submit", "apply now", "send application"]
    for line in snapshot.split("\n"):
        line_lower = line.lower()
        if "button" in line_lower and any(p in line_lower for p in submit_patterns):
            ref_match = re.search(r'\[ref=(e\d+)\]', line)
            if ref_match:
                ref = ref_match.group(1)
                human_delay(2, 4)
                browser(f"click {ref}")
                human_delay(3, 5)

                # Take confirmation screenshot
                snapshot_after = browser("snapshot")

                # Check for success
                success_signals = ["application submitted", "thank you", "we received",
                                   "successfully submitted", "application received"]
                if any(signal in snapshot_after.lower() for signal in success_signals):
                    take_screenshot_and_send(
                        job_id=job_id,
                        caption="✅ Application submitted successfully!"
                    )
                    return True
                else:
                    # Check for errors
                    take_screenshot_and_send(
                        job_id=job_id,
                        caption="⚠️ Submitted — please verify in screenshot"
                    )
                    return True

    send_message("❌ Could not find submit button — please submit manually")
    return False

def handle_linkedin_easy_apply(job: dict, resume_remote_path: str) -> bool:
    """
    LinkedIn Easy Apply uses shadow DOM — cannot be automated.
    Send LinkedIn URL directly for manual apply on mobile.
    """
    import requests
    import os

    job_id = job["id"]
    job_title = job.get("title", "")
    job_company = job.get("company", "")
    job_url = job.get("url", "")

    print(f"  [EASY APPLY] [{job_id[:8]}] LinkedIn Easy Apply — sending URL to user")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
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
                f"<b>{job_title}</b> at <b>{job_company}</b>\n\n"
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


def apply_to_job(job: dict, pdf_path: str) -> bool:
    """
    Main apply function.
    Finds apply URL, fills form, sends screenshot for review.
    Does NOT submit — waits for user confirmation.
    
    Returns True if form was filled and screenshot sent.
    """
    from dotenv import load_dotenv
    load_dotenv()

    candidate = get_candidate()
    job_id = job["id"]
    job_title = job.get("title", "Unknown")
    job_company = job.get("company", "Unknown")

    print(f"  [APPLY] Starting: {job_title} at {job_company} [{job_id[:8]}]")
    send_message(f"🤖 Starting application for <b>{job_title}</b> at <b>{job_company}</b>...")

    try:
        # Step 1 — Copy resume to Debian
        print(f"  [APPLY] [{job_id[:8]}] Copying resume to Debian...")
        resume_remote_path = copy_resume_to_debian(pdf_path)
        human_delay(1, 2)

        # Step 2 — Find real apply URL
        print(f"  [APPLY] [{job_id[:8]}] Finding apply URL...")
        apply_url, is_easy_apply, easy_apply_ref = get_real_apply_url(
            job.get("url", "")
        )

        # Step 3 — Navigate to application
        if is_easy_apply:
            print(f"  [APPLY] [{job_id[:8]}] LinkedIn Easy Apply flow...")
            send_message("📋 LinkedIn Easy Apply — handling multi-step form...")
            
            # Click the easy apply button/link if ref provided
            if easy_apply_ref:
                browser(f"click {easy_apply_ref}")
                human_delay(3, 5)
            
            # Handle multi-step Easy Apply
            return handle_linkedin_easy_apply(job, resume_remote_path)
        else:
            print(f"  [APPLY] [{job_id[:8]}] External ATS: {apply_url}")
            browser(f"open {apply_url}")
            human_delay(3, 5)

        # Step 4 — Get snapshot
        snapshot = browser("snapshot")

        # Step 5 — Check if stuck
        stuck = detect_stuck(snapshot)
        if stuck["stuck"]:
            print(f"  [APPLY] [{job_id[:8]}] Stuck: {stuck['type']}")
            send_stuck_notification(job, stuck)
            return False

        # Step 6 — Fill standard fields
        print(f"  [APPLY] [{job_id[:8]}] Filling standard fields...")
        fill_standard_fields(snapshot, candidate, resume_remote_path)
        human_delay(2, 4)

        # Step 7 — Upload resume
        print(f"  [APPLY] [{job_id[:8]}] Uploading resume...")
        snapshot = browser("snapshot")

        upload_patterns = [
            "upload file", "resume/cv", "upload resume",
            "choose file", "attach resume"
        ]
        for line in snapshot.split("\n"):
            line_lower = line.lower()
            if any(p in line_lower for p in upload_patterns) and "button" in line_lower:
                ref_match = re.search(r'\[ref=(e\d+)\]', line)
                if ref_match:
                    ref = ref_match.group(1)
                    print(f"  [APPLY] [{job_id[:8]}] Upload ref: {ref}")
                    browser(f"upload --input-ref {ref} {resume_remote_path}")
                    human_delay(1, 2)
                    browser(f"click {ref}")
                    human_delay(2, 3)
                    break

        # Step 8 — Answer screening questions
        print(f"  [APPLY] [{job_id[:8]}] Checking for screening questions...")
        snapshot = browser("snapshot")
        screening_patterns = [
            "in a few sentences", "describe", "tell us",
            "why do you", "how many years", "experience with"
        ]

        for line in snapshot.split("\n"):
            line_lower = line.lower()
            if "textbox" in line_lower and any(p in line_lower for p in screening_patterns):
                ref_match = re.search(r'\[ref=(e\d+)\]', line)
                if ref_match:
                    ref = ref_match.group(1)
                    question = line.split('"')[1] if '"' in line else "screening question"
                    print(f"  [APPLY] [{job_id[:8]}] Answering: {question[:60]}...")
                    answer = answer_screening_question(question, job)
                    browser(f'type {ref} "{answer}"')
                    human_delay(3, 5)

        # Step 9 — Take screenshot and send for review
        print(f"  [APPLY] [{job_id[:8]}] Taking screenshot for review...")
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

        # Step 10 — Send confirmation buttons
        from tools.notifier import send_apply_confirmation
        send_apply_confirmation(job)

        update_job_status(job_id, "ready_to_apply")
        print(f"  [APPLY] [{job_id[:8]}] Form ready — waiting for user confirmation")
        return True

    except Exception as e:
        print(f"  [APPLY ERROR] [{job_id[:8]}] {job_title} at {job_company}: {e}")
        send_message(
            f"❌ Apply failed for <b>{job_title}</b> at <b>{job_company}</b>\n"
            f"Error: {e}"
        )
        return False