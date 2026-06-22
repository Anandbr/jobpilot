import time
import schedule
from datetime import datetime
from tools.job_scraper import scan_for_new_jobs
from tools.scorer import score_job, quick_keyword_filter
from tools.tailor_resume import tailor_resume
from tools.notifier import send_job_notification, send_pdf, send_daily_summary, send_message
from tools.database import update_job_status, get_api_spend_today
from config.loader import get_job_search
import threading
import logging

logger = logging.getLogger(__name__)

def process_job(job: dict) -> bool:
    """
    Score job and notify if high match.
    Do NOT tailor automatically — wait for user to tap APPLY.
    """
    job_id = job["id"]
    jd_text = job.get("jd_text", "")

    if not jd_text:
        logger.info(f" [SKIP] No JD text for {job['title']}")
        return False
    
    # Score it
    logger.info(f"\n Processing: {job['title']} at {job['company']}")
    score_result = score_job(job_id=job_id, jd_text=jd_text)

    if not score_result:
        return False
    
    score = score_result.get("score", 0)
    min_score = get_job_search().get("min_score", 7.0)

    #Below threshold - skip
    if score < min_score:
        logger.info(f" [LOW_SCORE] {score}/10 - below threshold {min_score}")
        update_job_status(job_id, "low_score")
        return False

    logger.info(f" [HIGH_MATCH] {score}/10 - notifying user...")

    # Just notify — no tailoring yet
    sent = send_job_notification(
        job=job,
        score_result=score_result
    )

    if sent:
        update_job_status(job_id, "notified")
        logger.info(f"  ✅ Notified: {job['title']}")
        return True

    return False


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
    One full scan cycle.
    Find jobs -> process each one -> notify on matches
    """
    logger.info(f"\n{'='*50}")
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Starting scan...")
    logger.info(f"{'='*50}")

    try:
        #Find new jobs
        new_jobs = scan_for_new_jobs()

        if not new_jobs:
            print("[SCAN] No new jobs found this cycle")
            return
        
        #Process each job
        notified = 0
        for job in new_jobs:
            try:
                if process_job(job):
                    notified += 1
                    time.sleep(2) #Small delay between notifications
            except Exception as e:
                logger.error(f" [ERROR] Failed to process {job.get('title')}: {e}")
                continue
        
        logger.info(f"\n[SCAN COMPLETE] {notified} notifications sent "
              f"out pf {len(new_jobs)} new jobs")

        #Check budget
        spend = get_api_spend_today()
        logger.info(f"[BUDGET] Total API spend today: ${spend:.4f}")

    except Exception as e:
        logger.error(f"[SCAN_ERROR] {e}")
        send_message(f"⚠️ JobPilot scan error: {e}")

def send_evening_summary():
    """Send daily summary at 8pm."""
    from tools.database import get_connection
    import sqlite3

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
        WHERE date(discovered_at) = date('now')
    """)

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

    send_daily_summary(stats)

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

        except Exception as e:
            logger.error(f"[TELEGRAM LISTENER ERROR] {e}")
            time.sleep(5)

