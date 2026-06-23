"""
config/loader.py

Loads configuration and candidate data.
For multi-user: functions that take user_id read from DB.
For backwards compatibility: functions without user_id
still read from preferences.json (used for owner/testing).
"""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "preferences.json"

def _load_json() -> dict:
    """Load preferences.json — owner config and defaults."""
    with open(CONFIG_PATH) as f:
        return json.load(f)
    
def load_preferences() -> dict:
    """Full preferences.json — for backwards compatibility."""
    return _load_json()
    
def get_candidate() -> dict:
    """Owner candidate config from preferences.json."""
    return _load_json().get("candidate", {})

def get_job_search() -> dict:
    """Owner job search config from preferences.json."""
    return _load_json().get("job_search", {})

def get_resume_config() -> dict:
    """Resume config from preferences.json."""
    return _load_json().get("resume", {})

def get_budget_config() -> dict:
    """Budget config from preferences.json."""
    return _load_json().get("budget", {})

def get_notifications_config() -> dict:
    """Notifications config from preferences.json."""
    return _load_json().get("notifications", {})

# Multi user functions - read from DB
def get_job_search_for_user(user_id: str) -> dict:
    """
    Get job search preferences for a specific user from DB.

    Returns a dict in the same shape as get_job_search() so
    the scan loop can use either interchangeably.

    Falls back to preferences.json defaults for any field
    the user hasn't set yet.
    """
    from tools.database import get_job_preferences

    prefs = get_job_preferences(user_id)
    defaults = _load_json().get("job_search", {})

    return {
        "target_roles": (
            prefs["target_roles"] or
            defaults.get("target_roles", [])
        ),
        "role_keywords": (
            prefs["role_keywords"] or
            defaults.get("role_keywords", [])
        ),
        "locations": (
            prefs["locations"] or
            defaults.get("locations", [])
        ),
        "exclude_keywords": (
            prefs["exclude_keywords"] or
            defaults.get("exclude_keywords", [])
        ),
        "exclude_companies": (
            prefs["exclude_companies"] or
            defaults.get("exclude_companies", [])
        ),
        "min_salary": (
            prefs["min_salary"] or
            defaults.get("min_salary", 0)
        ),
        "min_score": (
            prefs["min_score"] or
            defaults.get("min_score", 7.0)
        ),
        "h1b_sponsorship_required": prefs["h1b_sponsorship_required"],
    }

def get_candidate_for_user(user: dict) -> dict:
    """
    Build candidate dict from a users table row.

    Used by tailor_resume and apply_to_job instead of
    reading from preferences.json — so each user's own
    profile is used, not the owner's.

    Args:
        user: dict from get_user_by_chat_id() or DB row
    """
    return {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "location": user.get("location", ""),
        "linkedin": user.get("linkedin_url", ""),
        "github": user.get("github_url", ""),
        "visa": user.get("visa_status", ""),
        "h1b_transfer_required": (
            "h1b" in user.get("visa_status", "").lower() or
            "sponsor" in user.get("visa_status", "").lower()
        ),
        "extended_experience": user.get("extended_experience", "")
    }