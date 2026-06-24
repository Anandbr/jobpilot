import time
import schedule
from datetime import datetime
from tools.job_scraper import scan_for_new_jobs
from tools.scorer import score_job, quick_keyword_filter
from tools.tailor_resume import tailor_resume
from tools.notifier import send_job_notification, send_pdf, send_daily_summary, send_message
from tools.database import update_job_status, get_api_spend_today, get_connection
from tools.registration import get_user_by_chat_id
from config.loader import get_job_search, get_job_search_for_user, get_candidate_for_user
import threading
import logging
import json
import os

logger = logging.getLogger(__name__)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http:localhost:11434")

def process_job_for_user(job: dict, user:dict,
                     user_candidate: dict, min_score: float,
                     api_key: str = None) -> dict | None:
    """
    Score a job against a specific user's profile.
    Returns score_result dict if above threshold, None if below.

    Why separate from process_job? — the old function used
    hardcoded global preferences. This one takes per-user
    candidate and preferences explicitly.
    """    
    user_prefs = get_job_search_for_user(user["id"])
    exclude_keywords = [
        k.lower() for k in user_prefs.get("exclude_keywords", [])
    ]
    exclude_companies = [
        c.lower() for c in user_prefs.get("exclude_companies", [])
    ]

    title_lower = job.get("title", "").lower()
    company_lower = job.get("company", "").lower()

    # Per-user exclusion filters — applied before hitting Claude
    if any(kw in title_lower for kw in exclude_keywords):
        logger.debug(
            f"[SCORE] Excluded by keyword | "
            f"job={job['title']} | user={user.get('name')}"
        )
        return None

    if any(c in company_lower for c in exclude_companies):
        logger.debug(
            f"[SCORE] Excluded company | "
            f"job={job['company']} | user={user.get('name')}"
        )
        return None
    
    job_id = job["id"]
    jd_text = job.get("jd_text", "")

    if not jd_text:
        logger.info(f" [SKIP] No JD text for {job['title']}")
        return None
    
    # Score it
    logger.info(
        f"[SCORE] Scoring | job={job['title']} | "
        f"user={user.get('name', 'unknown')} | "
        f"key={'user' if api_key else 'owner'}"
    )

    # Pass api_key through to scorer
    score_result = score_job(
        job_id=job_id,
        jd_text=jd_text,
        api_key=api_key,
        user=user
    )

    if not score_result:
        return None
    
    score = score_result.get("score", 0)

    #Below threshold - skip
    if score < min_score:
        update_job_status(job_id, "low_score")
        return None

    logger.info(
        f"[SCORE] Match | score={score}/10 | "
        f"job={job['title']} | user={user.get('name', 'unknown')}"
    )

    return score_result


    # #Tailor resume
    # tailored_text = tailor_resume(
    #     job_id=job_id,
    #     jd_text=jd_text,
    #     score_result=score_result
    # )

    # # Send notification
    # sent = send_job_notification(
    #     job=job,
    #     score_result=score_result,
    #     pdf_path=None
    # )

    # if sent:
    #     #Send pdf seperately if it exists
    #     from pathlib import Path
    #     pdf_path = Path(f"data/tailored_resumes/{job_id[:8]}_resume.pdf")
    #     if pdf_path.exists():
    #         send_pdf(
    #             str(pdf_path),
    #             caption=f"Tailored resume for {job['title']} at {job['company']}"
    #         )
        
    #     update_job_status(job_id, "notified")
    #     print(f"  ✅ Notification sent for {job['title']}")
    #     return True
    # return False
    
def run_scan():
    """
    One full scan cycle for ALL registered users.

    Flow:
    1. Get all registered users with their preferences
    2. Build combined search terms (scrape LinkedIn once)
    3. Score each job against each user's profile
    4. Notify each user of their matches
    5. Increment free tier counter per user
    """
    logger.info(f"\n{'='*50}")
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Starting scan...")
    logger.info(f"{'='*50}")

    # Pre-warm Ollama
    try:
        import requests as req
        req.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"), 
                "prompt": "hi", 
                "stream": False},
            timeout=60
        )
        logger.info("[SCAN] Ollama warmed up")
    except Exception as e:
        logger.warning(f"[SCAN] Ollama warm-up failed: {e}")


    try:
        # Step 1 - Get all registered users
        conn = get_connection()
        conn.row_factory = __import__('sqlite3').Row
        cursor = conn.cursor()
        cursor.execute("""SELECT * FROM users WHERE registration_status = 'complete'""")
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if not users:
            logger.info("[SCAN] No registered user(s) - skipping")
            return
        
        logger.info(f"[SCAN] {len(users)} registered user(s)")

        # Step. 2 - Build combined preferences across all users
        # This is what gets passed on to linkedin scraper
        # Union of all Users' locations and role keywords
        all_locations = set()
        all_keywords = set()

        for user in users:
            prefs = get_job_search_for_user(user["id"])
            for loc in prefs.get("locations", []):
                all_locations.add(loc)
            for kw in prefs.get("role_keywords", []):
                all_keywords.add(kw)

        combined_prefs = {
            "locations": list(all_locations),
            "role_keywords": list(all_keywords)
        }

        logger.info(
            f"[SCAN] Combined prefs | "
            f"locations={len(all_locations)} | "
            f"keywords={len(all_keywords)}"
        )

        # Step 3 — Scrape LinkedIn ONCE with combined prefs
        new_jobs = scan_for_new_jobs()

        if not new_jobs:
            print("[SCAN] No new jobs found this cycle")
            return
        
        logger.info(f"[SCAN] {len(new_jobs)} new jobs to process")

        # Step 4 - Score each job against each user
        for user in users:
            chat_id = user["telegram_chat_id"]
            user_prefs = get_job_search_for_user(user["id"])
            user_candidate = get_candidate_for_user(user)
            min_score = user_prefs.get("min_score", 7.0)
            user_locations = [
                l.lower() for l in user_prefs.get("locations", [])
            ]    
            # Get user's Claude API key (decrypted, in memory only)
            from tools.claude_client import get_user_claude_key
            api_key = get_user_claude_key(chat_id)

            #Check for free tier
            free_used = user.get("free_scan_runs_used", 0)
            free_cap = user.get("free_scan_runs_cap", 3)
            has_api_key = bool(api_key)

            if not has_api_key and free_used >= free_cap:
                logger.info(
                    f"[SCAN] Free tier exhausted | "
                    f"chat_id={chat_id} | used={free_used}/{free_cap}"
                )
                # Notify user once (not every cycle)
                # TODO: track whether we've already sent this notification
                continue
        
            #Process each job
            notified = 0
            for job in new_jobs:
                # Check if this job matches THIS user's location prefs
                job_location = job.get("location", "").lower()
                location_match = (
                    not user_locations or
                    any(loc in job_location for loc in user_locations) or
                    "remote" in job_location
                )

                if not location_match:
                    continue

                #Score against this user's profile
                try:
                    score_result = process_job_for_user(
                        job=job,
                        user=user,
                        user_candidate=user_candidate,
                        min_score=min_score,
                        api_key=api_key
                    )

                    if score_result:
                        # Notify this specific user
                        from tools.notifier import send_job_notification_to
                        send_job_notification_to(
                            chat_id=chat_id,
                            job=job,
                            score_result=score_result
                        )
                        notified += 1
                        time.sleep(2)
                except Exception as e:
                    logger.error(
                        f"[SCAN] Error processing job for user | "
                        f"chat_id={chat_id} | "
                        f"job={job.get('title')} | error={e}"
                    )
                    continue
            
            # Increment free tier counter for this user
            if not has_api_key:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users
                    SET free_scan_runs_used = free_scan_runs_used + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (user["id"],))
                conn.commit()
                conn.close()

                new_used = free_used + 1
                remaining = free_cap - new_used

                logger.info(
                    f"[SCAN] Free tier incremented | "
                    f"chat_id={chat_id} | "
                    f"used={new_used}/{free_cap}"
                )

                if remaining == 1:
                    from tools.notifier import send_message_to
                    send_message_to(
                        chat_id,
                        "⚠️ <b>Last free scan</b>\n\n"
                        "This was your second-to-last free scan run.\n"
                        "Add your Claude API key with /set-api-key "
                        "to keep getting job matches."
                    )
                elif remaining == 0:
                    from tools.notifier import send_message_to
                    send_message_to(
                        chat_id,
                        "🔒 <b>Free tier used up</b>\n\n"
                        "You've used all 3 free scan runs.\n"
                        "Add your Claude API key with /set-api-key "
                        "to continue getting job matches.\n\n"
                        "Get a key at: https://console.anthropic.com"
                    )

            logger.info(
                f"[SCAN] User complete | "
                f"chat_id={chat_id} | notified={notified}"
            )

        logger.info(f"[SCAN] Cycle complete | users={len(users)}")

        # Budget check
        spend = get_api_spend_today()
        logger.info(f"[BUDGET] API spend today: ${spend:.4f}")

    except Exception as e:
        logger.error(f"[SCAN ERROR] {e}")
        from tools.notifier import send_message
        send_message(f"⚠️ JobPilot scan error: {e}")       

def send_evening_summary():
    """Send daily summary to each registered user."""
    from tools.database import get_connection
    from tools.notifier import send_daily_summary

    conn = get_connection()
    conn.row_factory = __import__('sqlite3').Row
    cursor = conn.cursor()

    # Get all registered users
    cursor.execute("""
        SELECT * FROM users WHERE registration_status = 'complete'
    """)
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()


    for user in users:
        chat_id = user["telegram_chat_id"]
        user_id = user["id"]

        conn = get_connection()
        cursor = conn.cursor()
        # Get today's stats
        cursor.execute("""
            SELECT 
                COUNT(*) as scanned,
                SUM(CASE WHEN score >= 7 THEN 1 ELSE 0 END) as high_matches,
                SUM(CASE WHEN status = 'applied' THEN 1 ELSE 0 END) as applied,
                SUM(CASE WHEN status = 'skipped' THEN 1 else 0 END) as skipped
            FROM jobs
            WHERE user_id = ? AND date(discovered_at) = date('now')
        """, (user_id,))

        row = cursor.fetchone()
        conn.close()

        spend = get_api_spend_today()

        stats = {
            "scanned": row[0] or 0,
            "high_matches": row[1] or 0,
            "applied": row[2] or 0,
            "skipped": row[3] or 0,
            "api_spend": spend
        }

        send_daily_summary(
            chat_id=chat_id,
            stats=stats,
            user_name=user.get("name", "").split()[0]
        )

        logger.info(
            f"[SUMMARY] Sent | chat_id={chat_id} | "
            f"user={user.get('name')}"
        )

def start(run_once: bool = False):
    """
    Start the JobPilot agent.
    
    run_once=True   -> single scan then exit (for testing)
    run_once= False -> runs continuosly on schedule
    """

    from dotenv import load_dotenv
    load_dotenv()

    send_message("🚀 JobPilot agent started!")
    logger.info("\n[JOBPILOT] Starting agent...")

    #Start callback listener in background thread
    listener_thread = threading.Thread(
        target=start_callback_listener,
        daemon=True
    )
    listener_thread.start()

    if run_once:
        run_scan()
        return
    
    #Schedule scan every 30 minutes
    schedule.every(30).minutes.do(run_scan)

    #Daily summary at 8pm
    schedule.every().day.at("20:00").do(send_evening_summary)

    #Run immediately on start
    run_scan()

    logger.info("\n[JOBPILOT] Agent running. Scans every 30 minutes.")
    logger.info("Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(60)

def start_callback_listener():
    """
    Listen for telegram button callbacks in background thread.
    Handles APPLY and SKIP button
    """
    import requests
    import os
    from tools.notifier import handle_callback

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    base_url = f"https://api.telegram.org/bot{token}"
    last_update_id = 0

    logger.info("[TELEGRAM] Callback listener started")

    while True:
        try:
            response = requests.get(
                f"{base_url}/getUpdates",
                params={
                    "offset": last_update_id + 1,
                    "timeout": 5,
                    "allowed_updates": ["callback_query", "message"]
                },
                timeout=35
            )

            if response.status_code == 200:
                data = response.json()
                updates = data.get("result", [])

                for update in updates:
                    last_update_id = update["update_id"]
                    if "callback_query" in update:
                        handle_callback(update["callback_query"])
                    
                    elif "message" in update:
                        from tools.notifier import handle_message
                        handle_message(update["message"])

        except requests.exceptions.ReadTimeout:
            #Expected - Telegram long-poll timeout, just retry
            logger.debug("[TELEGRAM] Poll timeout - retrying")
            continue

        except Exception as e:
            logger.error(f"[TELEGRAM LISTENER ERROR] {e}")
            time.sleep(5)

