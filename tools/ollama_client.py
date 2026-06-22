import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

if not OLLAMA_BASE_URL:
    raise ValueError(
        "OLLAMA_BASE_URL not set in .env file. "
        "Add: OLLAMA_BASE_URL=http://your-server-ip:11434"
    )

def call_ollama(prompt: str, expect_json: bool = False) -> str:
    """
    Call local Ollama instance.
    Free - runs on your Debian server GPU.
    Use for simple classification tasks.
    """

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1, #Low temp for consistent outputs
                    "num_predict": 500 #Limit output length
                }
            },
            timeout=30
        )

        if response.status_code != 200:
            raise Exception(f"Ollama returned {response.status_code}")
        
        result = response.json()
        text = result.get("response", "").strip()

        if expect_json:
            # Clean up common JSON issues
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
        
        return text

    except requests.exceptions.ConnectionError:
        raise Exception(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            f"Is your Debian server running?"
        )
    except Exception as e:
        raise Exception(f"Ollama error: {e}")


def classify_email(subject: str, sender: str, preview: str) -> dict:
    """
    Classify an email as interview/rejection/followup/ignore.
    Uses local model - free.
    """
    prompt = f"""Classify this job application email. Return ONLY valid JSON.

    Subject: {subject}
    From: {sender}
    Preview: {preview}

    Classify as one of: interview_invite, rejection, followup_needed, phone_screen, ignored

    Return JSON only:
    {{"type": "interview_invite", "confidence": 0.95, "action_needed": true, "summary": "Interview scheduled for Tuesday"}}"""

    response = call_ollama(prompt, expect_json=True)

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"type": "ignored", "confidence": 0.5, "action_needed": False, "summary": ""}


def quick_relevance_check(job_title: str, company: str) -> bool:
    """
    Ultra fast check — is this job even worth fetching the full JD?
    Uses local model — free and fast.
    """
    prompt = f"""Is this a relevant software/AI engineering job for a senior engineer?
    Job: {job_title} at {company}

    Answer with just YES or NO."""

    response = call_ollama(prompt)
    return "YES" in response.upper()
