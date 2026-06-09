import os
from dotenv import load_dotenv

load_dotenv()

import anthropic
from config.loader import get_budget_config
from tools.database import get_api_spend_today, log_api_call

# Single Claude client instance - reads from .env
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

class BudgetExceededException(Exception):
    """Raised when daily API budget is exceeded"""
    pass

def call_claude(prompt: str, call_type: str,
                use_powerful_model: bool = False) -> str:
    """
    Single entry point for ALL Claude API call in JobPilot.
    
    This is the only place in the entire codebase that calls Claude.
    Budget check lives here and only here.
    
    Args:
    prompt: The full prompt to send
    call_type: Label for logging - "job_scoring", "resume_tailoring"
    use_powerful_model: False: Haiku (cheap), true = Sonnet (quality)
    
    Return:
    Claude's response as plain text
    
    Raises:
    BudgetExceededException: If daily limit reached
    """

    budget = get_budget_config()

    #Budget check - only place this lives
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

    # Select model
    if use_powerful_model:
        model = budget["tailoring_model"]
    else:
        model = budget["scoring_model"]

    # Make the API call
    response = client.messages.create(
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

    # Log it
    log_api_call(
        tokens=input_tokens + output_tokens,
        cost=cost,
        call_type=call_type
    )

    print(f"  💰 [{call_type}] model={model.split('-')[1]} | "
          f"tokens={input_tokens + output_tokens} | "
          f"cost=${cost:.5f} | "
          f"today=${spent_today + cost:.4f}")

    return response_text