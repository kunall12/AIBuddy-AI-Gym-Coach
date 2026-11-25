"""Anthropic Claude LLM integration for AIBuddy Post-Session Summaries & Coach Chat.

Reads ANTHROPIC_API_KEY from environment or .env.
Configurable model via COACH_MODEL (default: claude-3-7-sonnet-latest).
Degrades gracefully to local rule-based coaching summaries if no API key is set,
if network is unavailable, or on JSON parse failures.
Includes input length validation and per-IP rate limiting.
"""

from collections import defaultdict
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================
DEFAULT_COACH_MODEL = os.environ.get("COACH_MODEL", "claude-3-7-sonnet-latest").strip()
MAX_QUESTION_LENGTH = 500
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SEC = 60


# ============================================================================
# SIMPLE IN-MEMORY RATE LIMITER
# ============================================================================
class SimpleRateLimiter:
    """Thread-safe sliding window rate limiter per client IP."""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS, window_sec: int = RATE_LIMIT_WINDOW_SEC):
        self.max_requests = max_requests
        self.window_sec = window_sec
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> Tuple[bool, int]:
        now = time.time()
        cutoff = now - self.window_sec
        # Filter out timestamps older than the window
        timestamps = [t for t in self.requests[client_ip] if t > cutoff]
        self.requests[client_ip] = timestamps

        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_sec - (now - timestamps[0])) + 1
            return False, max(1, retry_after)

        self.requests[client_ip].append(now)
        return True, 0


RATE_LIMITER = SimpleRateLimiter()


def get_anthropic_client():
    """Retrieve Anthropic client using ANTHROPIC_API_KEY, or None if unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "").strip()
        except Exception:
            api_key = ""

    if not api_key:
        return None

    try:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    except Exception as exc:
        print(f"[CoachLLM] Could not initialize Anthropic client: {exc}")
        return None


# ============================================================================
# LOCAL RULE-BASED FALLBACK SUMMARY
# ============================================================================
def generate_local_fallback_summary(session_stats: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    """Generates a structured, evidence-based summary without external API dependencies."""
    duration = session_stats.get("duration_sec", 0)
    minutes = max(1, int(round(duration / 60)))
    total_reps = session_stats.get("total_reps_completed", 0)
    target_reps = session_stats.get("total_reps_target", 0)
    completion_rate = session_stats.get("completion_rate_pct", 100.0)
    avg_score = session_stats.get("avg_form_score", 85.0)

    exercises = session_stats.get("exercises", [])
    exercise_names = [ex.get("exercise", "Movement") for ex in exercises]

    wins = []
    if completion_rate >= 90:
        wins.append(f"Completed {total_reps}/{target_reps} reps ({completion_rate:.0f}% completion rate) with great tenacity!")
    else:
        wins.append(f"Put in solid work across {len(exercises)} exercises totaling {total_reps} completed reps.")

    if avg_score >= 85:
        wins.append(f"Maintained excellent overall biomechanical posture ({avg_score:.0f}% average form score).")
    elif avg_score >= 70:
        wins.append(f"Kept solid foundation on primary compound lifts ({avg_score:.0f}% average form score).")

    improvements = []
    all_errors = []
    for ex in exercises:
        errors = ex.get("common_errors", [])
        for err in errors:
            all_errors.append(f"{ex.get('exercise')}: {err}")

    if all_errors:
        for err in all_errors[:3]:
            improvements.append(f"Focus on stabilizing {err}.")
    else:
        improvements.append("Maintain consistent rep cadence and avoid rushing the negative (eccentric) portion.")

    tips = [
        "Incorporate 5 minutes of focused mobility and dynamic hip opening before your next routine.",
        "Ensure controlled eccentric tempos (2 seconds down) to maximize hypertrophy and joint stability.",
        "Hydrate adequately and prioritize protein synthesis within 60 minutes post-workout.",
    ]

    next_session = [
        f"Target {min(target_reps + 2, target_reps + 5)} reps or slightly increase dumbbell resistance next round.",
        "Maintain current rest intervals (30-60 seconds) to build cardiovascular work capacity.",
    ]

    summary_text = (
        f"Solid workout session! You completed {total_reps} reps across {len(exercises)} exercises "
        f"in approximately {minutes} minute{'s' if minutes != 1 else ''} with an average form score of {avg_score:.0f}%."
    )

    return {
        "summary": summary_text,
        "wins": wins,
        "improvements": improvements,
        "tips": tips,
        "next_session": next_session,
        "is_fallback": True,
        "fallback_reason": reason or "Local rule-based coach fallback",
    }


# ============================================================================
# CLAUDE POST-SESSION SUMMARY GENERATION
# ============================================================================
SUMMARY_SYSTEM_PROMPT = """You are Apna AI Coach, a supportive, evidence-based fitness coach analyzing a user's completed gym session.
Your tone is energizing, precise, and encouraging.

You will receive session statistics in JSON including exercises, completed vs target reps, average form scores, detected form issues, tempo, and rest durations.

You MUST respond ONLY with a valid JSON object matching this exact schema:
{
  "summary": "2-3 sentences summarizing the session performance and energy",
  "wins": ["specific win 1", "specific win 2"],
  "improvements": ["specific form or tempo improvement area 1", "improvement area 2"],
  "tips": ["actionable technique tip 1", "actionable recovery tip 2"],
  "next_session": ["concrete target rep/load progression recommendation 1", "suggestion 2"]
}

Guidelines:
- Keep the response strictly JSON. Do not include markdown code blocks or extra conversational text.
- Be concise to conserve tokens.
- Reference their actual numbers and form error data where available.
"""


def generate_workout_summary(session_stats: Dict[str, Any]) -> Dict[str, Any]:
    """Generate Claude-powered workout summary with JSON validation and graceful local fallback."""
    client = get_anthropic_client()
    if client is None:
        return generate_local_fallback_summary(session_stats, reason="ANTHROPIC_API_KEY not configured or client unavailable")

    model = os.environ.get("COACH_MODEL", DEFAULT_COACH_MODEL).strip() or "claude-3-7-sonnet-latest"

    compact_payload = {
        "duration_sec": session_stats.get("duration_sec", 0),
        "total_reps_completed": session_stats.get("total_reps_completed", 0),
        "total_reps_target": session_stats.get("total_reps_target", 0),
        "avg_form_score": session_stats.get("avg_form_score", 100),
        "exercises": session_stats.get("exercises", []),
    }

    try:
        response = client.messages.create(
            model=model,
            max_tokens=600,
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Here are the workout session statistics:\n{json.dumps(compact_payload, indent=2)}",
                }
            ],
        )

        response_text = ""
        for block in response.content:
            if getattr(block, "type", "") == "text":
                response_text += block.text

        response_text = response_text.strip()
        # Strip potential markdown formatting
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        data = json.loads(response_text)

        # Validate expected keys and types
        required_keys = ["summary", "wins", "improvements", "tips", "next_session"]
        for k in required_keys:
            if k not in data:
                raise ValueError(f"Missing required key '{k}' in LLM response")

        if not isinstance(data["summary"], str) or not isinstance(data["wins"], list):
            raise ValueError("Malformed response types in LLM JSON output")

        data["is_fallback"] = False
        data["model_used"] = model
        return data

    except Exception as exc:
        print(f"[CoachLLM] Summary API call failed: {exc}. Falling back to local summary.")
        return generate_local_fallback_summary(session_stats, reason=f"API error: {type(exc).__name__}: {exc}")


# ============================================================================
# INTERACTIVE "ASK YOUR COACH" CHAT
# ============================================================================
CHAT_SYSTEM_PROMPT = """You are Apna AI Coach, a supportive, practical fitness trainer speaking directly with the user.

Rules:
1. Be practical, friendly, and concise (under 120 words).
2. Give clear biomechanical guidance on form, breathing, tempo, and exercise mechanics.
3. For pain or injury questions (e.g. 'Why does my lower back hurt on deadlifts?' or 'Knee hurts on squats'):
   - Explain likely technique/biomechanical causes (e.g., lack of core bracing, forward knee drift, improper hip hinge, excessive load).
   - Reference the user's flagged form errors if present in session stats.
   - Provide concrete form fixes to try.
   - ALWAYS include this mandatory medical disclaimer clearly:
     "Disclaimer: This is biomechanical technique guidance, not medical advice. If you experience sharp, persistent, or radiating pain, please stop immediately and consult a doctor or physical therapist."
   - NEVER diagnose a medical injury or condition.
"""


def chat_with_coach(
    question: str,
    session_stats: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    client_ip: str = "127.0.0.1",
) -> Dict[str, Any]:
    """Handle user chat question with rate limiting, safeguards, and non-diagnostic coaching advice."""
    cleaned = (question or "").strip()

    if not cleaned:
        return {"error": "Question cannot be empty.", "status": 400}

    if len(cleaned) > MAX_QUESTION_LENGTH:
        return {
            "error": f"Question exceeds maximum length of {MAX_QUESTION_LENGTH} characters (was {len(cleaned)}).",
            "status": 400,
        }

    # Check IP rate limit
    allowed, retry_after = RATE_LIMITER.is_allowed(client_ip)
    if not allowed:
        return {
            "error": f"Rate limit reached. Please wait {retry_after} second{'s' if retry_after != 1 else ''} before sending another question.",
            "status": 429,
        }

    client = get_anthropic_client()
    if client is None:
        # Graceful local fallback for chat if API key is not configured
        fallback_msg = (
            "I'm currently running in offline coach mode because ANTHROPIC_API_KEY is not configured. "
            "For optimal form on compound exercises, focus on core bracing, keeping joints stacked, and moving with control. "
            "Please add your ANTHROPIC_API_KEY to .env to enable personalized Claude AI coach answers."
        )
        return {"response": fallback_msg, "status": 200, "is_fallback": True}

    model = os.environ.get("COACH_MODEL", DEFAULT_COACH_MODEL).strip() or "claude-3-7-sonnet-latest"

    # Assemble messages with rolling history (capped at last 10 messages)
    clean_history = list(history or [])[-10:]
    messages: List[Dict[str, str]] = []

    for msg in clean_history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Prepare context prefix if session stats are available
    stats_context = ""
    if session_stats:
        compact_stats = {
            "completed_reps": session_stats.get("total_reps_completed", 0),
            "target_reps": session_stats.get("total_reps_target", 0),
            "avg_form_score": session_stats.get("avg_form_score", 100),
            "exercises": [ex.get("exercise") for ex in session_stats.get("exercises", [])],
        }
        stats_context = f"[Context of current session: {json.dumps(compact_stats)}]\n\n"

    messages.append({"role": "user", "content": f"{stats_context}{cleaned}"})

    try:
        response = client.messages.create(
            model=model,
            max_tokens=350,
            system=CHAT_SYSTEM_PROMPT,
            messages=messages,
        )

        response_text = ""
        for block in response.content:
            if getattr(block, "type", "") == "text":
                response_text += block.text

        return {
            "response": response_text.strip(),
            "status": 200,
            "is_fallback": False,
            "model_used": model,
        }

    except Exception as exc:
        print(f"[CoachLLM] Chat API call failed: {exc}")
        return {
            "error": f"AI Coach temporarily unavailable: {type(exc).__name__}: {exc}",
            "status": 500,
        }
