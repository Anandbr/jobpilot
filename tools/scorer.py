import json
import logging
from tools.database import job_already_scored, save_score, save_job
from tools.claude_client import call_claude, BudgetExceededException
from tools.resume_builder import read_base_resume
from harness.skill_loader import (
    render_skill,load_candidate_context, load_extended_expereince,
    load_candidate_context_for_user, load_extended_experience_for_user
)
from config.loader import get_job_search

logger = logging.getLogger(__name__)

def quick_keyword_filter(jd_text: str, prefs: dict = None) -> bool:
    """
    Level 1 filter - no api calls.
    Returns True if job passes basic keyword search.

    Args:
        jd_text: Job description text
        prefs: Job search preferences dict. If None, uses owner
               preferences from preferences.json (backwards compat).

    Why accept prefs? — for multi-user, each user has different
    role_keywords and exclude_keywords. Passing prefs here lets
    the scan loop filter per-user without hardcoding.
    """
    if prefs is None:
        prefs = get_job_search()
    jd_lower = jd_text.lower()

    #Must match atleast one role keyword
    role_keywords = prefs.get("role_keywords", [])
    role_match = any(
        keyword in jd_lower
        for keyword in role_keywords
    )
    if not role_match:
        return False
    
    #Must not contain exclude keywords
    exclude_keywords = prefs.get("exclude_keywords", [])
    excluded = any(
        keyword in jd_lower
        for keyword in exclude_keywords
    )
    if excluded:
        return False
    
    return True

def score_job(job_id: str, jd_text: str,
              api_key: str = None,
              user: dict = None) -> dict | None:
    """
    Score a job against candidate profile.
    
    Returns score dict or None if skipped/cached/budget exceeded.

    Args:
        job_id: Unique job identifier
        jd_text: Full job description text
        api_key: User's own Claude API key if set.
                 If None, uses owner key with budget check.
        user: User dict from DB. If None, falls back to 
                owner files (candidate-context.md)
    
    Flow:
    1. Cache check - already scored? Return None
    2. Keyword filter - passes basic check
    3. Load skill + context + resume
    4. Call Claude (with user key if provided)
    5. Parse result, save to database
    """

    #1. Cache check
    if job_already_scored(job_id):
        logger.debug(f"[SCORE] Cache hit | job_id={job_id[:8]}")
        return None
    
    #2. Keyword filter
    if not quick_keyword_filter(jd_text):
        logger.debug(f"[SCORE] Failed keyword filter | job_id={job_id[:8]}")
        return None
    
    #3. # Load context — from DB user row if available, else files
    if user:
        candidate_context = load_candidate_context_for_user(user)
        extended_experience = load_extended_experience_for_user(user)
    else:
        candidate_context = load_candidate_context()
        extended_experience = load_extended_expereince()

    base_resume = read_base_resume()

    prompt = render_skill(
        "score-job-fit",
        candidate_context=candidate_context,
        extended_experience=extended_experience if extended_experience 
                        else "No additional experience context provided.",
        jd_text=jd_text
    )

    #Save job to database forst so score can be linked to it.
    save_job({
        "id": job_id,
        "title": "Unknown",
        "company": "Unknown", 
        "location": "Unknown",
        "jd_text": jd_text,
        "source": "manual_test"
    })

    #4. Call Claude
    try:
        response_text = call_claude(
            prompt=prompt,
            call_type="job_scoring",
            use_powerful_model=False, #Haiku 
            api_key=api_key #None = Owner key, str = user key
        )

        #Clean response
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        result = json.loads(clean)
    
    except BudgetExceededException as e:
        print(f" [BUDGET] {e}")
        return None
    
    except json.JSONDecodeError as e:
        print(f" [ERROR] Claude returned invalid JSON: {e}")
        print(f" Raw response: {response_text[:200]}")
        return None
    
    except Exception as e:
        print(f" [ERROR] Scoring failed: {e}")
        return None
    
    #5 Save to database
    save_score(
        job_id=job_id,
        score=result["score"],
        reasoning=result["recommendation"],
        strong_matches=result.get("strong_matches", []),
        gaps=result.get("gaps", [])
    )

    logger.info(f"  ✅ Score: {result['score']}/10 — {result['one_line_summary']}")
    logger.info(f"  Apply: {result.get('apply', False)} | "
          f"Priority: {result.get('priority', 'normal')}")

    return result