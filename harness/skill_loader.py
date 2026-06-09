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
    
def load_candidate_context() -> str:
    """Load the candidate context file."""
    return load_data_file("candidate-context.md")

def load_extended_expereince() -> str:
    return load_data_file("extended-experience.md")