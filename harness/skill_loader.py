from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "skills"
DATA_DIR = Path(__file__).parent.parent / "data"

def load_skill(skill_name: str) -> str:
    """Load a skill file by name without .md extension."""
    skill_path = SKILLS_DIR / f"{skill_name}.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill not found: {skill_name}")
    return skill_path.read_text()

def load_data_file(filename: str) -> str:
    """Load a file from the data directory."""
    file_path = DATA_DIR / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Data file not found: {filename}")
    return file_path.read_text()

def render_skill(skill_name: str, **kwargs) -> str:
    """
    Load a skill and fill in variables.

    Example:
        render_skill(
            "score-job-fit",
            candidate_context="...",
            extended_experience="...",
            jd_text="..."
        )
    """
    template = load_skill(skill_name)
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise ValueError(f"Skill '{skill_name}' requires variable {e}")

# Backwards compatible functions (read from files)    
def load_candidate_context() -> str:
    """
    Load the candidate context file.
    testing only — for multi-user use
    load_candidate_context_for_user(user) instead.
    """
    return load_data_file("candidate-context.md")

def load_extended_expereince() -> str:
    """
    Load extended experience from file.
    testing only — for multi-user use
    load_extended_experience_for_user(user) instead.
    """
    return load_data_file("extended-experience.md")

# Multi user functions - build context from DB user row
def load_candidate_context_for_user(user: dict) -> str:
    """
    Build candidate context string from a DB user row.

    This replaces reading candidate-context.md for multi-user.
    The same information is now stored in the users table,
    collected during registration.

    Args:
        user: dict from get_user_by_chat_id() or DB row

    Returns:
        Formatted string matching the shape of candidate-context.md
        so existing skill templates work without modification.
    """
    name = user.get("name", "")
    email = user.get("email", "")
    phone = user.get("phone", "")
    location = user.get("location", "")
    linkedin = user.get("linkedin_url", "")
    github = user.get("github_url", "") or "Not provided"
    visa = user.get("visa_status", "")
    salary = user.get("salary_expectation", "") or "Not specified"

    return f"""# Candidate Profile
    name = user.get("name", "")
    email = user.get("email", "")
    phone = user.get("phone", "")
    location = user.get("location", "")
    linkedin = user.get("linkedin_url", "")
    github = user.get("github_url", "") or "Not provided"
    visa = user.get("visa_status", "")
    salary = user.get("salary_expectation", "") or "Not specified"

    return f"""# Candidate Profile

def load_extended_experience_for_user(user: dict) -> str:
    """
    Load extended experience from DB user row.

    This replaces reading extended-experience.md for multi-user.
    Content is added via /experience-update Telegram command.

    Args:
        user: dict from get_user_by_chat_id() or DB row

    Returns:
        Extended experience text, or empty string if none added yet.
    """
    return user.get("extended_experience", "") or ""
