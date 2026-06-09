import json
import hashlib
from tools.database import job_already_scored, save_score, save_job
from tools.claude_client import call_claude, BudgetExceededException
from tools.resume_builder import read_base_resume
from harness.skill_loader import render_skill, load_candidate_context, load_extended_expereince
from config.loader import get_job_search

def quick_keyword_filter(jd_text: str) -> bool:
    """
    Level 1 filter - no api calls.
    Returns True if job passes basic keyword search.
    """
    preferences = get_job_search()
    jd_lower = jd_text.lower()

    #Must match atleast one role keyword
    role_match = any(
        keyword in jd_lower
        for keyword in preferences["role_keywords"]
    )
    if not role_match:
        return False
    
    #Must not contain exclude keywords
    excluded = any(
        keyword in jd_lower
        for keyword in preferences["exclude_keywords"]
    )
    if excluded:
        return False
    
    return True

def score_job(job_id: str, jd_text: str) -> dict | None:
    """
    Score a job against candidate profile.
    
    Returns score dict or None if skipped/cached/budget exceeded.
    
    Flow:
    1. Cache check - already scored? Return None
    2. Keyword filter - passes basic check
    3. Load skill + context + resume
    4. Call Claude 
    5. Parse result, save to database
    """

    #1. Cache check
    if job_already_scored(job_id):
        print(f" [CACHE] Already scored - skipping API call")
        return None
    
    #2. Keyword filter
    if not quick_keyword_filter(jd_text):
        print(f" [FILTERED] Failed keyword check - skipping")
        return None
    
    #3. Load everything needed
    candidate_context = load_candidate_context()
    extended_expereince = load_extended_expereince()
    base_resume = read_base_resume()

    prompt = render_skill(
        "score-job-fit",
        candidate_context=candidate_context,
        extended_experience=extended_expereince,
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
            use_powerful_model=False #Haiku 
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

    print(f"  ✅ Score: {result['score']}/10 — {result['one_line_summary']}")
    print(f"  Apply: {result.get('apply', False)} | "
          f"Priority: {result.get('priority', 'normal')}")

    return result