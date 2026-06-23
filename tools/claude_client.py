import os
from dotenv import load_dotenv
import logging

load_dotenv()

import anthropic
from config.loader import get_budget_config
from tools.database import get_api_spend_today, log_api_call

logger = logging.getLogger(__name__)

# Owner client — used for free tier and fallback
# Created once at module load, uses .env key
_owner_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

class BudgetExceededException(Exception):
    """Raised when daily API budget is exceeded"""
    pass

def _get_client(api_key: str = None) -> anthropic.Anthropic:
    """
    Return the right Claude client for this request.

    If api_key provided — create a client with the user's own key.
    If not — use the shared owner client from .env.

    Why create per-request for user keys? — anthropic.Anthropic()
    is lightweight to instantiate and we don't want to cache
    per-user clients (memory, and keys can be deleted anytime).
    """
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    return _owner_client

def get_user_claude_key(chat_id: str) -> str | None:
    """
    Retrieve and decrypt a user's Claude API key from DB.
    Returns None if user has no ket set.
    
    Called by runner.py before passing to call_claude().
    Decryption happens here - the plain key is only in memory
    during the API call, never logged or stored unencrypted.
    """
    from tools.registration import get_user_by_chat_id
    from tools.crypto import decrypt_secret

    user = get_user_by_chat_id(str(chat_id))
    if not user:
        return None
    
    encrypted = user.get("claude_api_key_encrypted")
    if not encrypted:
        return None
    
    try:
        return decrypt_secret(encrypted)
    except Exception as e:
        logger.error(
            f"[CLAUDE] Failed to decrypt API key | "
            f"chat_id={chat_id} | error={e}"
        )
        return None

def call_claude(prompt: str, call_type: str,
                use_powerful_model: bool = False,
                api_key: str = None) -> str:
    """
    Single entry point for ALL Claude API call in JobPilot.
    
    This is the only place in the entire codebase that calls Claude.
    Budget check lives here and only here.
    
    Args:
    prompt: The full prompt to send
    call_type: Label for logging — 'job_scoring', 'resume_tailoring'
    use_powerful_model: False=Haiku (cheap), True=Sonnet (quality)
    api_key: User's own Claude API key if set.
    If None, uses owner key from .env with budget check.
    
    Return:
    Claude's response as plain text
    
    Raises:
    BudgetExceededException: If daily limit reached (owner key only)
    """

    budget = get_budget_config()

    #Budget check - only applies to OWNER key as of now
    if not api_key:
        spent_today = get_api_spend_today()

        if spent_today >= budget["daily_limit_usd"]:
            raise BudgetExceededException(
                f"Daily budget ${budget['daily_limit_usd']} reached. "
                f"Spent today: ${spent_today:.4f}. "
                f"API calls paused until tomorrow."
            )
    
        # Warn if approaching limit
        if spent_today >= budget["alert_at_usd"]:
            print(f"  ⚠️  [BUDGET WARNING] ${spent_today:.4f} spent — "
                f"approaching ${budget['daily_limit_usd']} limit")
    else:
        spent_today = 0 # not tracking for user keys

    # Select model
    model = (
        budget["tailoring_model"]
        if use_powerful_model
        else budget["scoring_model"]
    )

    # Get the right client
    claude = _get_client(api_key)

    # Make the API call
    response = claude.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    # Extract text
    response_text = response.content[0].text.strip()

    # Calculate cost
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    if "haiku" in model:
        cost = (input_tokens * 0.00000025 +
                output_tokens * 0.00000125)
    else:
        cost = (input_tokens * 0.000003 +
                output_tokens * 0.000015)

     # Log API call — only tracks owner key spend
    # User key spend is on their own Anthropic account
    if not api_key:
        log_api_call(
            tokens=input_tokens + output_tokens,
            cost=cost,
            call_type=call_type
        )


    logger.info(f"  💰 [{call_type}] model={model.split('-')[1]} | "
          f"tokens={input_tokens + output_tokens} | "
          f"cost=${cost:.5f} | "
          f"today=${spent_today + cost:.4f}")

    return response_text