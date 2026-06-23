import os
import requests
from dotenv import load_dotenv
import logging
from pathlib import Path
from tools.registration import (
    handle_registration_message,
    is_registered,
    get_user_by_chat_id
)

logger = logging.getLogger(__name__)
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send_message_to(chat_id: str, text: str,
                    keyboard: dict = None) -> bool:
    """ Send a message to specific chat ID. """
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    
    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json=payload,
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"[NOTIFIER] send_message_to failed | "
                     f"chat_id={chat_id} | error={e}")
        return False


#This is v0 where chatId is hardcoded for testing, this function will be removed later.
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

def send_job_notification_to(chat_id: str, job: dict,
                               score_result: dict) -> bool:
    """
    Send a job match notification to a SPECIFIC user.
    Multi-user version of send_job_notification().
    """
    score = score_result.get("score", 0)
    company = job.get("company", "Unknown")
    title = job.get("title", "Unknown")
    location = job.get("location", "Unknown")
    url = job.get("url", "")

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

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ APPLY",
             "callback_data": f"apply_{job['id']}"},
            {"text": "❌ SKIP",
             "callback_data": f"skip_{job['id']}"},
            {"text": "👀 VIEW", "url": url}
        ]]
    }

    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": str(chat_id),
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
                "disable_web_page_preview": False
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(
            f"[NOTIFIER] send_job_notification_to failed | "
            f"chat_id={chat_id} | error={e}"
        )
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

def download_telegram_file(file_id: str, save_path: str) -> bool:
    """
    Download a file from Telegram using its file_id.
    Saves to save_path onloacl_disk.

    telegram stores uploaded files on their servers.
    file_id is just a reference. to actually use the file
    (to upload to ATS or to read it while scoring), we need real bytes on disk.

    Returns True if downloaded successfully.
    """
    import requests as req

    try:
        #Step 1 - Get the file path from Telegram
        response = req.get(
            f"{BASE_URL}/getFile",
            params={"file_id": file_id},
            timeout=10
        )
        data = response.json()

        if not data.get("ok"):
            logger.error(
                f"[TELEGRAM] getFile failed | "
                f"file_id={file_id[:20]} | response={data}"
            )
            return False
        
        file_path = data["result"]["file_path"]

        # Step 2 - Download actual file bytes
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        download_url = (
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )

        file_response = req.get(download_url, timeout=30)
        if file_response.status_code != 200:
            logger.error(
                f"[TELEGRAM] Download failed | "
                f"status={file_response.status_code}"
            )
            return False
        
        # Step 3 - Save to disk
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(file_response.content)
        
        logger.info(
            f"[TELEGRAM] File downloaded | "
            f"path={save_path} | "
            f"size={len(file_response.content)} bytes"
        )
        return True
    except Exception as e:
        logger.error(f"[TELEGRAM] Download error | error={e}")
        return False

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

def handle_message(message: dict) -> None:
    """
    Route an incoming Telegram message to the right handler.
    
    Called by polling loop for every non-callback message.
    
    Routing logic:
    1. Extract chat_id and text from the message.
    2. If user is not registered -> registration flow.
    3. If user is registered -> check for commands,
        otherwise ignore (job notifications handle themselves)
    """
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()
    document = message.get("document")

    if not chat_id:
        logger.warning("[NOTIFIER] Message received with no chat_id")
        return

    logger.info(f"[NOTIFIER] Message recieved | chat_id={chat_id} | "
                f"text={text[:30] if text else 'document'}")
    
    #Check if User is fully registered
    user = get_user_by_chat_id(chat_id)
    is_complete = user and user.get("registration_status") == "complete"

    # NOT REGISTERED -> registration flow
    if not is_complete:
        reply = handle_registration_message(
            chat_id=chat_id,
            text=text,
            document=document
        )
        if reply:
            send_message_to(chat_id, reply)
        return
    
    #Check for pending confirmations first
    pending = user.get("pending_confirmation", "") or ""
    if pending == "awaiting_api_key" and text and not text.startswith("/"):
        #This message is the API key - encrypt and store it
        _handle_api_key_submission(chat_id, text)
        return
    
    elif pending.startswith("awaiting_update_") and not text.startswith("/"):
        field = pending.replace("awaiting_update_", "")
        _handle_update_value_received(
            chat_id=chat_id,
            field=field,
            text=text,
            document=document
        )
        return

    # REGISTERED -> handle commands
    if text.startswith("/experience-update"):
        _handle_experience_update(chat_id, text)
    
    elif text.startswith("/experience-reset"):
        _handle_experience_reset_request(chat_id)
    
    elif text.startswith("/set-api-key"):
        _handle_set_api_key_request(chat_id)
    
    elif text.startswith("/delete-api-key"):
        _handle_delete_api_key(chat_id)

    elif text.startswith("/profile-update"):
        _handle_profile_update(chat_id)
    
    elif text.startswith("/profile"):
        _handle_profile(chat_id)
    
    elif text.startswith("/skip"):
        # /skip during registration is handled in registration
        # If they're registered, /skip means nothing
        pass

    else:
        #Registered user sent a non-command text message
        # Probably an accidental message - ignore silently
        logger.debug(f"[NOTIFIER] Unhandled text from registered user | "
                     f"chat_id={chat_id} | text={text[:30]}")
        
def _handle_experience_update(chat_id: str, text: str) -> None:
    """ Append to user's extended_experience field. """
    #Strip the command prefix to get just the content
    content = text.replace("/experience-update", "").strip()

    if not content:
        send_message_to(
            chat_id,
            "Tell me what to add to your experience - send it "
            "as: \n\n /experience-update <your experience here>"
        )
        return
    
    from tools.database import get_connection
    from datetime import datetime

    #Append with timestamp so the ahgent knows when things happened
    timestamp = datetime.utcnow().strftime("%Y-%m-%d")
    entry = f"\n\n[{timestamp}]\n{content}"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
            UPDATE users SET extended_experience = extended_experience || ?,
            updated_at = CURRENT_TIMESTAMP WHERE telegram_chat_id = ?""", (entry, chat_id))
    conn.commit()
    conn.close()

    logger.info(f"[EXPERIENCE] Updated | chat_id={chat_id} | "
                f"chars_added={len(content)}")
    send_message_to(
        chat_id,
        "✅ Added to your experience profile.\n\n"
        "I'll use this when tailoring resumes and answering "
        "screening questions for your next matches."
    )

def _handle_experience_reset_request(chat_id: str) -> None:
    """
    Ask for confirmation before wiping extended_experience.
    Sends inline button - actual reset only happens if
    user taps the confirm button.
    """
    keyboard = {
        "inline_keyboard": [[
            {
                "text": "⚠️ Yes, reset everything",
                "callback_data": f"confirm_experience_reset_{chat_id}"
            },
            {
                "text": "❌ Cancel",
                "callback_data": f"cancel_experience_reset_{chat_id}"
            }
        ]]
    }
    send_message_to(
        chat_id,
        "⚠️ <b>Are you sure?</b>\n\n"
        "This will permanently delete all your extended "
        "experience — everything added via /experience-update.\n\n"
        "Your basic profile (name, email, resume) is not affected.",
        keyboard=keyboard
    )

def _handle_set_api_key_request(chat_id: str) -> None:
    """
    Prompt user to send their Claude API Key.
    Sets a pending state so that next message is treated as the key.
    """
    from tools.database import get_connection

    # Set pending state - next message from this user is their API key
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
            UPDATE users SET pending_confirmation = 'awaiting_api_key',
            updated_at = CURRENT_TIMESTAMP WHERE telegram_chat_id = ?
            """, (chat_id,))
    conn.commit()
    conn.close()

    send_message_to(
        chat_id,
        "🔑 <b>Set your Claude API key</b>\n\n"
        "Send your Anthropic API key in the next message.\n\n"
        "Your key is encrypted before storage and used only "
        "for your own requests — We never share or log it.\n\n"
        "Get a key at: https://console.anthropic.com\n\n"
        "<i>Tip: delete the message after sending for extra safety</i>"
    )

def _handle_delete_api_key(chat_id: str) -> None:
    """Wipe the users stored Claude API Key."""
    from tools.database import get_connection
    from tools.registration import get_user_by_chat_id

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
            UPDATE users SET claude_api_key_encrypted = NULL,
            updated_at = CURRENT_TIMESTAMP WHERE TELEGRAM_CHAT_ID = ?
            """, (chat_id,))
    conn.commit()
    conn.close()

    # Get actual remaining free runs — don't assume 3
    user = get_user_by_chat_id(chat_id)
    used = user.get("free_scan_runs_used", 0) if user else 0
    cap = user.get("free_scan_runs_cap", 3) if user else 3
    remaining = max(0, cap - used)

    logger.info(f"[API KEY] Deleted | chat_id={chat_id} | "
                f"free_runs_remaining={remaining}")
    if remaining > 0:
        free_tier_msg = (
            f"You have {remaining} free scan run(s) remaining.\n"
            f"Use /set-api-key to add a new key anytime."
        )
    else:
        free_tier_msg = (
            "You've used all your free scan runs.\n"
            "Use /set-api-key to add a new key to continue."
        )

    send_message_to(
        chat_id,
        f"🗑️ API key deleted.\n\n{free_tier_msg}"
    )

def _handle_api_key_submission(chat_id: str, api_key: str) -> None:
    """
    User just sent their Claude API key as a plain text message.
    Encrypt it and store it. Clear the pending state.
    """
    from tools.crypto import encrypt_secret
    from tools.database import get_connection

    # Basic sanity check — Anthropic keys start with sk-ant-
    if not api_key.startswith("sk-ant-"):
        send_message_to(
            chat_id,
            "That doesn't look like a valid Anthropic API key.\n\n"
            "Keys start with 'sk-ant-'. Try again or use "
            "/set-api-key to restart."
        )
        return

    encrypted = encrypt_secret(api_key)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users
        SET claude_api_key_encrypted = ?,
            pending_confirmation = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_chat_id = ?
    """, (encrypted, chat_id))
    conn.commit()
    conn.close()

    logger.info(f"[API KEY] Set successfully | chat_id={chat_id}")
    send_message_to(
        chat_id,
        "✅ API key saved and encrypted.\n\n"
        "All your job scans and resume tailoring will now "
        "use your own Claude account.\n\n"
        "Use /delete-api-key to remove it anytime."
    )

def _handle_profile(chat_id: str) -> None:
    """Show the user what's stored on their profile."""
    from tools.registration import get_user_by_chat_id

    user = get_user_by_chat_id(chat_id)
    if not user:
        send_message_to(chat_id, "❌ Profile not found.")
        return

    has_key = bool(user.get("claude_api_key_encrypted"))
    free_runs = user.get("free_scan_runs_used", 0)
    free_cap = user.get("free_scan_runs_cap", 3)
    exp = user.get("extended_experience", "")
    exp_preview = exp[:100] + "..." if len(exp) > 100 else exp or "None added yet"

    send_message_to(
        chat_id,
        f"👤 <b>Your Profile</b>\n\n"
        f"Name: {user.get('name', '—')}\n"
        f"Email: {user.get('email', '—')}\n"
        f"Location: {user.get('location', '—')}\n"
        f"Visa: {user.get('visa_status', '—')}\n"
        f"Salary: {user.get('salary_expectation', '—')}\n"
        f"LinkedIn: {user.get('linkedin_url', '—')}\n"
        f"GitHub: {user.get('github_url', '—') or 'Not set'}\n\n"
        f"Claude API key: {'✅ Set' if has_key else '❌ Not set'}\n"
        f"Free scans used: {free_runs}/{free_cap}\n\n"
        f"<b>Experience preview:</b>\n{exp_preview}"
    )

def _handle_profile_update(chat_id: str) -> None:
    """
    Show profile field selection button.
    Called on /profile-update command or "Yes, update more" tap.
    """
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "👤 Name",
                 "callback_data": f"update_field_name|{chat_id}"},
                {"text": "📧 Email",
                 "callback_data": f"update_field_email|{chat_id}"},
                {"text": "📱 Phone",
                 "callback_data": f"update_field_phone|{chat_id}"},
            ],
            [
                {"text": "📍 Location",
                 "callback_data": f"update_field_location|{chat_id}"},
                {"text": "💼 LinkedIn",
                 "callback_data": f"update_field_linkedin_url|{chat_id}"},
                {"text": "💻 GitHub",
                 "callback_data": f"update_field_github_url|{chat_id}"},
            ],
            [
                {"text": "🛂 Visa Status",
                 "callback_data": f"update_field_visa_status|{chat_id}"},
                {"text": "💰 Salary",
                 "callback_data": f"update_field_salary_expectation|{chat_id}"},
                {"text": "📄 Resume",
                 "callback_data": f"update_field_base_resume|{chat_id}"},
            ]
        ]
    }
    send_message_to(
        chat_id,
        "✏️ <b>Update your profile</b>\n\n"
        "Which field would you like to update?",
        keyboard=keyboard
    )

def _handle_update_field_selected(chat_id: str, field: str) -> None:
    """
    User tapped a field button.
    Set pending state and ask for the new value.
    """ 
    from tools.database import get_connection

    field_prompts = {
        "name": "What's your new full legal name?",
        "email": "What's your new email address?",
        "phone": "What's your new phone number? (include country code)",
        "location": "What city and country are you based in now?",
        "linkedin_url": "What's your new LinkedIn profile URL?",
        "github_url": "What's your new GitHub URL? (or /skip)",
        "visa_status": "What's your current work authorization status?",
        "salary_expectation": "What's your salary expectation? (include currency)",
        "base_resume": "Please send your new resume as a PDF file."
    }

    prompt = field_prompts.get(field, f"What's your new {field}?")

    #Set pending state - next non-command message = new value
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
            UPDATE users SET pending_confirmation = ?,
            updated_at = CURRENT_TIMESTAMP WHERE
            telegram_chat_id = ?
            """, (f"awaiting_update_{field}", chat_id))
    conn.commit()
    conn.close()

    logger.info(f"[PROFILE UPDATE] Awaiting input | "
                f"chat_id={chat_id} | field={field}"
                )
    send_message_to(chat_id, prompt)
    
def _handle_update_value_received(chat_id: str, field: str,
                                  text: str = None, document = None) -> None:
    """
    User sent new value - Validate, save, confirm, 
    then ask if they want to update anything else.
    """
    from tools.database import get_connection
    from tools.registration import _validate_step

    #Resume is a document upload
    if field == "base_resume":
        if not document:
            send_message_to(
                chat_id,
                "Please send your resume as a PDF file - "
                "tap the 📎 attachment button."
            )
            return
        
        file_id = document.get("file_id", "")

        #Get user_id for path
        from tools.registration import get_user_by_chat_id
        user = get_user_by_chat_id(chat_id)
        user_id = user["id"] if user else chat_id

        save_path = f"data/resumes/{user_id}/base_resume.pdf"
        downloaded = download_telegram_file(file_id, save_path)

        if not downloaded:
            send_message_to(
                chat_id,
                "⚠️ Failed to save your resume — please try again."
            )
            return
        value = save_path
    else:
        if not text or not text.strip():
            send_message_to(chat_id, "I didn't get that - please try again.")
            return
        
        #Handle /skip for optional fields
        if text.strip().lower() == "/skip" and field in ["github_url"]:
            value = ""
        else:
            value = text.strip()
            #Reuse registration validation
            error = _validate_step(field, value)
            if error:
                send_message_to(chat_id, error)
                return
    
    #Map step key to DB column name
    FIELD_TO_COLUMN = {
        "base_resume": "base_resume",
        "linkedin_url": "linkedin_url",
        "github_url": "github_url",
        "visa_status": "visa_status",
        "salary_expectation": "salary_expectation",
    }
    db_column = FIELD_TO_COLUMN.get(field, field)

    #Save to DB and clear pending state
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
            UPDATE users SET {db_column} = ?,
            pending_confirmation = NULL,
            updated_at = CURRENT_TIMESTAMP WHERE
            telegram_chat_id = ?
            """, (value, chat_id))
    conn.commit()
    conn.close()

    logger.info(f"[PROFILE UPDATE] Saved |"
                f"chat_id={chat_id} | field = {field}"
                )
    
    # Human-readable field label for confirmation
    field_labels = {
        "name": "Name",
        "email": "Email",
        "phone": "Phone",
        "location": "Location",
        "linkedin_url": "LinkedIn",
        "github_url": "GitHub",
        "visa_status": "Visa status",
        "salary_expectation": "Salary expectation",
        "base_resume": "Resume"
    }
    label = field_labels.get(field, field)

    if field == "base_resume":
        confirm_text = f"✅ {label} updated."
    else:
        confirm_text = f"✅ {label} updated to <b>{value}</b>"

    # Ask if they want to update anything else
    keyboard = {
        "inline_keyboard": [[
            {
                "text": "✏️ Yes, update more",
                "callback_data": f"update_more_|{chat_id}"
            },
            {
                "text": "✅ Done",
                "callback_data": f"update_done_|{chat_id}"
            }
        ]]
    }

    send_message_to(
        chat_id,
        f"{confirm_text}\n\nWould you like to update anything else?",
        keyboard=keyboard
    )    

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
    
    print(f"[CALLBACK] Received: '{data}'")

    if data.startswith("confirm_experience_reset_"):
        chat_id = data.replace("confirm_experience_reset_", "")
        from tools.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET extended_experience = '',
                pending_confirmation = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_chat_id = ?
        """, (chat_id,))
        conn.commit()
        conn.close()
        logger.info(f"[EXPERIENCE] Reset | chat_id={chat_id}")
        send_message_to(chat_id, "✅ Experience reset. Start fresh with /experience-update")

    elif data.startswith("cancel_experience_reset_"):
        chat_id = data.replace("cancel_experience_reset_", "")
        send_message_to(chat_id, "Cancelled — your experience is unchanged.")
    
    elif data.startswith("update_field_"):
        # format: "update_field_{field}|{chat_id}"
        without_prefix = data.replace("update_field_", "")
        field, chat_id = without_prefix.split("|", 1)
        _handle_update_field_selected(chat_id, field)

    elif data.startswith("update_more_|"):
        chat_id = data.replace("update_more_|", "")
        _handle_profile_update(chat_id)

    elif data.startswith("update_done_|"):
        chat_id = data.replace("update_done_|", "")
        send_message_to(
            chat_id,
            "✅ Profile saved.\n\nUse /profile to review your details."
        )
    
    elif data.startswith("apply_"):
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