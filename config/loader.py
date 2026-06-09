import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "preferences.json"

def load_preferences() -> dict:
    """Load preferences from JSON file."""
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)
    
def get_candidate() -> dict:
    return load_preferences()["candidate"]

def get_job_search() -> dict:
    return load_preferences()["job_search"]

def get_resume_config() -> dict:
    return load_preferences()["resume"]

def get_budget_config() -> dict:
    return load_preferences()["budget"]

def get_notifications_config() -> dict:
    return load_preferences()["notifications"]