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
        send_message(
            f"🚀 Submitting application...\n"
            f"OpenClaw integration coming soon!\n\n"
            f"For now — open the job link and apply manually.\n"
            f"Job ID: {job_id[:8]}"
        )
        from tools.database import update_job_status
        update_job_status(job_id, "applied") #todo: maybe change this status from openclaw once it is actually applied
    
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


def _handle_apply(job_id: str) -> None:
    """Tailor resume and prepare application when user taps APPLY."""
    from tools.database import get_job
    from tools.tailor_resume import tailor_resume

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
    from pathlib import Path
    pdf_path = Path(f"data/tailored_resumes/{job_id[:8]}_resume.pdf")

    if pdf_path.exists():
        send_pdf(
            str(pdf_path),
            caption=f"📄 Tailored for {job['title']} at {job['company']}"
        )

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