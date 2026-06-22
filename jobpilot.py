import sys
import argparse
from harness.runner import start, run_scan
from tools.database import get_connection, get_api_spend_today
from tools.metrics import start_metrics_server
import logging
import os

def setup_logging():
    """
    Console-only logging for now.
    File rotation added later.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logging.info("JobPilot Starting up...")

def cmd_start():
    """Start the agent continuosly."""
    start(run_once=False)

def cmd_scan():
    """Run one scan and exit."""
    start(run_once=True)

def cmd_listen():
    # Telegram listener only — no scanning
        # Perfect for testing registration flow
        from harness.runner import start_callback_listener
        from tools.notifier import send_message
        import threading
        print("[JOBPILOT] Listen-only mode — no scanning")
        send_message("👂 JobPilot listening (no scan)")
        start_callback_listener()

def cmd_status():
    """Show current pipeline status."""
    conn = get_connection()
    cursor = conn.cursor()

    print("\n" + "=" * 50)
    print("JOBPILOT STATUS")
    print("=" * 50)

    # Today's jobs
    cursor.execute("""
        SELECT COUNT(*) FROM jobs
        WHERE date(discovered_at) = date('now')
    """)
    today_count = cursor.fetchone()[0]

    # High matches
    cursor.execute("""
        SELECT COUNT(*) FROM jobs
        WHERE score >= 7.0
        AND date(discovered_at) = date('now')
    """)
    high_matches = cursor.fetchone()[0]

    # Notified
    cursor.execute("""
        SELECT COUNT(*) FROM jobs
        WHERE status = 'notified'
        AND date(discovered_at) = date('now')
    """)
    notified = cursor.fetchone()[0]

    # Applied
    cursor.execute("""
        SELECT COUNT(*) FROM jobs
        WHERE status = 'applied'
    """)
    applied_total = cursor.fetchone()[0]

    # Top matches today
    cursor.execute("""
        SELECT title, company, score, url
        FROM jobs
        WHERE score >= 7.0
        AND date(discovered_at) = date('now')
        ORDER BY score DESC
        LIMIT 5
    """)
    top_jobs = cursor.fetchall()
    conn.close()

    spend = get_api_spend_today()

    print(f"Jobs found today:     {today_count}")
    print(f"High matches (7+):    {high_matches}")
    print(f"Notified:             {notified}")
    print(f"Applied total:        {applied_total}")
    print(f"API spend today:      ${spend:.4f}")
    print(f"\nTop matches today:")

    for job in top_jobs:
        print(f"  {job[2]}/10 — {job[0]} at {job[1]}")
        print(f"         {job[3][:60]}...")

    print("=" * 50)

if __name__ == "__main__":
    start_metrics_server()
    parser = argparse.ArgumentParser(description="JobPilot - AI Job Agent")
    parser.add_argument(
        "command",
        choices=["start", "scan", "status", "listen"],
        help="start=run continuosly | scan = one scan | status = check pipeline | listen = listen for message from user"
    )
    args = parser.parse_args()

    if args.command == "start":
        cmd_start()
    elif args.command == "scan":
        cmd_scan()
    elif args.command == "status":
        cmd_status()
    elif args.command == "listen":
        cmd_listen()
