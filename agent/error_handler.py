import json
import re
import sys
from pathlib import Path
from enum import Enum


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


class ErrorDecision(Enum):
    RETRY       = "retry"      
    SKIP        = "skip"       
    REPLAN      = "replan"     
    ABORT       = "abort"    


ERROR_ANALYST_PROMPT = """You are the error recovery module of NIANG IA assistant.

A task step has failed. Analyze the error and decide what to do.

DECISIONS:
- retry   : Transient error (network timeout, temporary file lock, race condition).
             The same step can succeed if tried again.
- skip    : This step is not critical and the task can succeed without it.
- replan  : The approach was wrong. A different tool or method should be tried.
- abort   : The task is fundamentally impossible or unsafe to continue.

Also provide:
- A brief explanation of WHY it failed (1 sentence)
- A fix suggestion if decision is replan (what to try instead)
- Max retries: how many times to retry if decision is retry (1 or 2)

Return ONLY valid JSON:
{
  "decision": "retry|skip|replan|abort",
  "reason": "why it failed",
  "fix_suggestion": "what to try instead (for replan)",
  "max_retries": 1,
  "user_message": "Short message to tell the user (max 15 words)"
}
"""

def _safe_error_summary(error: str) -> str:
    lowered = str(error).casefold()
    if "blocked for safety" in lowered or "safety policy" in lowered:
        return "The action was blocked by the safety policy."
    if "timeout" in lowered or "timed out" in lowered:
        return "The action timed out."
    if any(term in lowered for term in ("permission", "access denied", "unauthorized")):
        return "The action was denied by permissions."
    if any(term in lowered for term in ("not found", "no such element", "missing element")):
        return "The requested element or resource was not found."
    status = re.search(r"\bhttp(?: status)?\s*[:=]?\s*(\d{3})\b", lowered)
    if status:
        return f"The remote server returned HTTP status {status.group(1)}."
    if any(term in lowered for term in ("network", "connection", "dns", "net::err")):
        return "A network connection failed."
    if any(term in lowered for term in ("unsupported", "invalid argument", "invalid url")):
        return "The action used an unsupported or invalid argument."
    return "The action failed; exact details are omitted."


def _safe_step_metadata(step: dict) -> tuple[str, str, bool]:
    parameters = step.get("parameters", {})
    action = parameters.get("action", "") if isinstance(parameters, dict) else ""
    tool = str(step.get("tool", "unknown"))
    action = str(action)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", tool):
        tool = "unknown"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", action):
        action = ""
    return (
        tool,
        action,
        bool(step.get("critical", False)),
    )


def analyze_error(
    step: dict,
    error: str,
    attempt: int = 1,
    max_attempts: int = 2
) -> dict:
    """
    Analyzes a failed step and returns a recovery decision.

    Args:
        step         : The step dict that failed
        error        : Error message/traceback
        attempt      : Current attempt number
        max_attempts : How many times we've already tried

    Returns:
        {
            "decision": ErrorDecision,
            "reason": str,
            "fix_suggestion": str,
            "max_retries": int,
            "user_message": str
        }
    """
    from api_keys import GeminiModel

    if attempt >= max_attempts:
        print(f"[ErrorHandler] ⚠️ Max attempts reached for step {step.get('step')} — forcing replan")
        return {
            "decision":      ErrorDecision.REPLAN,
            "reason":        f"Failed {attempt} times. {_safe_error_summary(error)}",
            "fix_suggestion": "Try a completely different approach or tool",
            "max_retries":   0,
            "user_message":  "Trying a different approach, sir."
        }

    model = GeminiModel(
        model_name="gemini-3.5-flash-lite",
        system_instruction=ERROR_ANALYST_PROMPT
    )

    tool, action, critical = _safe_step_metadata(step)
    prompt = f"""Failed step:
Tool: {tool}
Action: {action or '(unspecified)'}
Critical: {critical}

Error summary:
{_safe_error_summary(error)}

Attempt number: {attempt}"""

    try:
        response = model.generate_content(prompt)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        result = json.loads(text)
        decision_str = result.get("decision", "replan").lower()
        decision_map = {
            "retry":  ErrorDecision.RETRY,
            "skip":   ErrorDecision.SKIP,
            "replan": ErrorDecision.REPLAN,
            "abort":  ErrorDecision.ABORT,
        }
        result["decision"] = decision_map.get(decision_str, ErrorDecision.REPLAN)


        if step.get("critical") and result["decision"] == ErrorDecision.SKIP:
            result["decision"]     = ErrorDecision.REPLAN
            result["user_message"] = "This step is critical — finding alternative approach, sir."

        print(f"[ErrorHandler] Recovery decision: {result['decision'].value}")
        return result

    except Exception:
        print("[ErrorHandler] Recovery analysis failed; defaulting to replan.")
        return {
            "decision":       ErrorDecision.REPLAN,
            "reason":         "Recovery analysis failed.",
            "fix_suggestion": "Try alternative approach",
            "max_retries":    1,
            "user_message":   "Encountered an issue, adjusting approach, sir."
        }


def generate_fix(step: dict, error: str, fix_suggestion: str) -> dict:
    """
    When decision is REPLAN and a fix suggestion exists,
    generates a replacement step using generated_code as fallback.

    Returns a modified step dict.
    """
    from api_keys import GeminiModel

    model = GeminiModel(model_name="gemini-2.0-flash")

    tool, action, _ = _safe_step_metadata(step)
    prompt = f"""A task step failed. Generate a replacement step.

Tool: {tool}
Action: {action or '(unspecified)'}

Error summary: {_safe_error_summary(error)}
Fix suggestion: {fix_suggestion}

Write a Python script that accomplishes the same goal differently.
Return ONLY the Python code, no explanation."""

    try:
        response = model.generate_content(prompt)
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        return {
            "step":        step.get("step"),
            "tool":        "code_helper",
            "description": f"Alternative for {tool} action",
            "parameters": {
                "action":      "run",
                "description": fix_suggestion,
                "code":        code,
                "language":    "python"
            },
            "depends_on": step.get("depends_on", []),
            "critical":   step.get("critical", False)
        }

    except Exception:
        print("[ErrorHandler] Recovery action generation failed.")
        return {
            "step":        step.get("step"),
            "tool":        "generated_code",
            "description": f"Fallback for {tool} action",
            "parameters":  {"description": f"Alternative for {tool} action"},
            "depends_on":  step.get("depends_on", []),
            "critical":    step.get("critical", False)
        }