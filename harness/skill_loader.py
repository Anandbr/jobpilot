from pathlib import Path
import logging

logger = logging.getLogger(__name__)

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
    """Load a skill template and fill in variables."""
    template = load_skill(skill_name)
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise ValueError(f"Skill '{skill_name}' requires variable {e}")


def load_candidate_context() -> str:
    """Owner only — reads from candidate-context.md file."""
    return load_data_file("candidate-context.md")


def load_extended_expereince() -> str:
    """Owner only — reads from extended-experience.md file."""
    return load_data_file("extended-experience.md")


def load_candidate_context_for_user(user: dict) -> str:
    """Build candidate context from DB user row."""
    name = user.get("name", "")
    email = user.get("email", "")
    phone = user.get("phone", "")
    location = user.get("location", "")
    linkedin = user.get("linkedin_url", "")
    github = user.get("github_url", "") or "Not provided"
    visa = user.get("visa_status", "")
    salary = user.get("salary_expectation", "") or "Not specified"

    return f"""# Candidate Profile

## Personal Information
- Name: {name}
- Email: {email}
- Phone: {phone}
- Location: {location}
- LinkedIn: {linkedin}
- GitHub: {github}

## Work Authorization
- Status: {visa}

## Salary Expectation
- {salary}
"""


def load_extended_experience_for_user(user: dict) -> str:
    """Load extended experience from DB user row."""
    return user.get("extended_experience", "") or ""