import os
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_message(text: str) -> bool:
    """Send a plain text message."""
    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")
        return False


def send_job_notification(job: dict, score_result: dict,
                          pdf_path: str = None) -> bool:
    """
    Send a job match notification with Apply/Skip inline buttons.
    """
    score = score_result.get("score", 0)
    company = job.get("company", "Unknown")
    title = job.get("title", "Unknown")
    location = job.get("location", "Unknown")
    url = job.get("url", "")

    # Build matches and gaps text
    matches = score_result.get("strong_matches", [])[:3]
    gaps = score_result.get("gaps", [])[:2]

    matches_text = "\n".join(f"✅ {m}" for m in matches)
    gaps_text = "\n".join(f"⚠️ {g}" for g in gaps)

    message = (
        f"🎯 <b>NEW JOB MATCH — {score}/10</b>\n\n"
        f"<b>{title}</b>\n"
        f"🏢 {company}\n"
        f"📍 {location}\n\n"
        f"<b>Strong Matches:</b>\n{matches_text}\n\n"
        f"<b>Gaps:</b>\n{gaps_text}\n\n"
        f"🔗 <a href='{url}'>View Job</a>"
    )

    # Inline keyboard buttons
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ APPLY", "callback_data": f"apply_{job['id']}"},
            {"text": "❌ SKIP",  "callback_data": f"skip_{job['id']}"},
            {"text": "👀 VIEW",  "url": url}
        ]]
    }

    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
                "disable_web_page_preview": False
            },
            timeout=10
        )
        return response.status_code == 200

    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")
        return False


def send_pdf(pdf_path: str, caption: str = "Your tailored resume") -> bool:
    """Send the tailored resume PDF."""
    try:
        with open(pdf_path, "rb") as f:
            response = requests.post(
                f"{BASE_URL}/sendDocument",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption
                },
                files={"document": f},
                timeout=30
            )
        return response.status_code == 200
    except Exception as e:
        print(f"  [TELEGRAM PDF ERROR] {e}")
        return False


def send_daily_summary(stats: dict) -> bool:
    """Send end of day summary."""
    message = (
        f"📊 <b>JobPilot Daily Report</b>\n\n"
        f"Jobs scanned: {stats.get('scanned', 0)}\n"
        f"High matches (7+): {stats.get('high_matches', 0)}\n"
        f"Applied: {stats.get('applied', 0)}\n"
        f"Skipped: {stats.get('skipped', 0)}\n"
        f"API spend today: ${stats.get('api_spend', 0):.3f}\n\n"
        f"Keep going Anand! 💪"
    )
    return send_message(message)

def send_apply_confirmation(job: dict) -> bool:
    """Send final confirmation buttons after screenshot is sent."""
    message = (
        f"👆 Review the screenshot above carefully.\n\n"
        f"Tap <b>SUBMIT NOW</b> to submit the application\n"
        f"or <b>CANCEL</b> to abort."
    )

    keyboard = {
        "inline_keyboard": [[
            {
                "text": "🚀 SUBMIT NOW",
                "callback_data": f"submit_{job['id']}"
            },
            {
                "text": "❌ CANCEL",
                "callback_data": f"cancel_{job['id']}"
            }
        ]]
    }

    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": keyboard
            },
            timeout=10
        )
        return True
    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")
        return False
    
def send_photo(photo_path: str, caption: str = "") -> bool:
    """Send a photo to Telegram."""
    try:
        with open(photo_path, "rb") as f:
            response = requests.post(
                f"{BASE_URL}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=30
            )
        return response.status_code == 200
    except Exception as e:
        print(f"  [TELEGRAM PHOTO ERROR] {e}")
        return False
    
def handle_callback(callback_query: dict) -> None:
    """
    Handle button taps from Telegram.
    Called when user taps APPLY or SKIP.
    """
    data = callback_query.get("data", "")
    callback_id = callback_query.get("id")

    #Acknowledge the callback immediately
    requests.post(
        f"{BASE_URL}/answerCallbackQuery",
        json={"callback_query_id": callback_id},
        timeout=5
    )

    if data.startswith("apply_"):
        job_id = data.replace("apply_", "")
        send_message(f"✅ Got it! Tailoring resume for job {job_id[:8]}...")
        _handle_apply(job_id)

    elif data.startswith("skip_"):
        job_id = data.replace("skip_", "")
        send_message(f"⏭️ Skipped job {job_id[:8]}")
        _handle_skip(job_id)

    elif data.startswith("confirm_"):
        job_id = data.replace("confirm_", "")
        send_message("🚀 Submitting application...")
        _handle_confirm_submit(job_id)

    elif data.startswith("continue_"):
        job_id = data.replace("continue_", "")
        send_message("✅ Continuing application...")
        from tools.database import get_job
        from pathlib import Path
        from tools.apply import apply_to_job
        job = get_job(job_id)
        pdf_path = Path(f"data/tailored_resumes/{job_id[:8]}_resume.pdf")
        if job and pdf_path.exists():
            apply_to_job(job=job, pdf_path=str(pdf_path))
        else:
            send_message("❌ Job or resume not found")
    
    
    elif data.startswith("modify_"):
        job_id = data.replace("modify", "")
        send_message(
            f"✏️ Resume modification coming soon!\n\n"
            f"For now — tap CONFIRM SUBMIT to proceed with "
            f"the current tailored resume, or CANCEL to skip."
        )
    
    elif data.startswith("cancel_"):
        job_id = data.replace("cancel_", "")
        from tools.database import update_job_status
        update_job_status(job_id, "skipped")
        send_message(f"❌ Application cancelled.")

    elif data.startswith("applied_"):
        job_id = data.replace("applied_", "")
        from tools.database import update_job_status, get_job
        job = get_job(job_id)
        update_job_status(job_id, "applied")
        if job:
            send_message(
                f"✅ <b>Logged as applied!</b>\n\n"
                f"<b>{job['title']}</b> at <b>{job['company']}</b>\n\n"
                f"Good luck! 🤞"
            )
    
    elif data.startswith("submit_"):
        job_id = data.replace("submit_", "")
        send_message("🚀 Submitting now...")
        from tools.apply import submit_application
        from tools.database import update_job_status, get_job
        job = get_job(job_id)
        if job:
            result = submit_application(job_id)
            if result:
                update_job_status(job_id, "applied")
                send_message(
                    f"✅ Application submitted!\n"
                    f"<b>{job['title']}</b> at <b>{job['company']}</b>\n"
                    f"Good luck! 🤞"
                )
            else:
                send_message(f"❌ Submit failed — apply manually\n{job.get('url', '')}")

def _handle_confirm_submit(job_id: str):
    """
    User tapped CONFIRM — start filling the form.
    Does NOT submit yet — waits for second confirmation.
    """
    from tools.database import get_job
    from tools.apply import apply_to_job
    from pathlib import Path

    job = get_job(job_id)
    if not job:
        send_message("❌ Job not found in database")
        return

    pdf_path = Path(f"data/tailored_resumes/{job_id[:8]}_resume.pdf")
    if not pdf_path.exists():
        send_message(f"❌ Resume PDF not found")
        return

    send_message(
        f"🤖 Filling application form for\n"
        f"<b>{job['title']}</b> at <b>{job['company']}</b>\n\n"
        f"Will send screenshot when ready..."
    )

    # Fill the form — does NOT submit
    apply_to_job(job=job, pdf_path=str(pdf_path))

def _handle_apply(job_id: str) -> None:
    """Tailor resume and prepare application when user taps APPLY."""
    from tools.database import get_job
    from tools.tailor_resume import tailor_resume
    from tools.apply import apply_to_job
    from pathlib import Path
    import json

    job = get_job(job_id)
    if not job:
        send_message(f"❌ Job {job_id[:8]} not found in database")
        return
    
    send_message(f"🎨 Tailoring resume for {job['title']} at {job['company']}...")

    # Get existing score from database
    import json
    score_result = {
        "score": job.get("score", 8),
        "recommendation": job.get("score_reasoning", ""),
        "strong_matches": json.loads(job.get("strong_matches", "[]")),
        "gaps": json.loads(job.get("gaps", "[]")),
        "transferable": []
    }

    # Tailor resume
    tailored = tailor_resume(
        job_id=job_id,
        jd_text=job.get("jd_text", ""),
        score_result=score_result
    )

    if not tailored:
        send_message("❌ Resume tailoring failed")
        return
    
    # Send PDF
    pdf_path = Path(f"data/tailored_resumes/{job_id[:8]}_resume.pdf")
    print(f"  [PDF] Looking for: {pdf_path}")
    print(f"  [PDF] Exists: {pdf_path.exists()}")

    if pdf_path.exists():
        result = send_pdf(
            str(pdf_path),
            caption=f"📄 Tailored for {job['title']} at {job['company']}"
        )
        print(f"  [PDF] Send result: {result}")
    else:
        send_message("⚠️ PDF not found — resume text was generated but PDF conversion may have failed") 
    from tools.database import update_job_status
    update_job_status(job_id, "ready_to_apply")

    message = (
        f"✅ Resume ready!\n\n"
        f"<b>{job['title']}</b> at <b>{job['company']}</b>\n"
        f"🔗 {job.get('url', '')}\n\n"
        f"Next: OpenClaw will handle the application.\n"
        f"Tap below to confirm submission."
    )

    keyboard = {
        "inline_keyboard": [[
            {
                "text": "🚀 CONFIRM SUBMIT",
                "callback_data": f"confirm_{job_id}"
            },
            {
                "text": "✏️ MODIFY RESUME",
                "callback_data": f"modify_{job_id}"
            },
            {
                "text": "❌ CANCEL",
                "callback_data": f"cancel_{job_id}"
            }
        ]]
    }

    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
                "disable_web_page_preview": False
            },
            timeout=10
        )
    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")


def _handle_skip(job_id: str) -> None:
    """Mark job as skipped."""
    from tools.database import update_job_status
    update_job_status(job_id, "skipped")