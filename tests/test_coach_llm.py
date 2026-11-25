"""Unit tests for Claude Coach LLM, JSON validation, fallback summaries, and chat safeguards."""

from unittest.mock import MagicMock
import pytest

from services.coach_llm import (
    generate_local_fallback_summary,
    generate_workout_summary,
    chat_with_coach,
    SimpleRateLimiter,
)


def test_local_fallback_summary_schema():
    """Verify local fallback summary adheres to the required structured schema."""
    stats = {
        "duration_sec": 720,
        "total_reps_completed": 36,
        "total_reps_target": 40,
        "completion_rate_pct": 90.0,
        "avg_form_score": 88.0,
        "exercises": [
            {"exercise": "Squats", "reps_completed": 20, "common_errors": ["Too high depth"]},
            {"exercise": "Push-ups", "reps_completed": 16, "common_errors": []},
        ],
    }
    summary = generate_local_fallback_summary(stats, reason="Test fallback")
    assert isinstance(summary["summary"], str)
    assert len(summary["summary"]) > 0
    assert isinstance(summary["wins"], list) and len(summary["wins"]) > 0
    assert isinstance(summary["improvements"], list)
    assert isinstance(summary["tips"], list) and len(summary["tips"]) > 0
    assert isinstance(summary["next_session"], list) and len(summary["next_session"]) > 0
    assert summary["is_fallback"] is True


def test_generate_workout_summary_with_mocked_claude_success(monkeypatch):
    """Verify successful Claude response parsing with valid JSON."""
    mock_client = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = """{
        "summary": "Tremendous session with crisp squats and explosive tempo.",
        "wins": ["Maintained full parallel depth on all squat sets.", "Steady breathing rhythm."],
        "improvements": ["Control eccentric descent on push-ups."],
        "tips": ["Keep elbows tucked at 45 degrees.", "Hydrate well."],
        "next_session": ["Add 2 reps to squats next workout."]
    }"""
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_client.messages.create.return_value = mock_response

    monkeypatch.setattr("services.coach_llm.get_anthropic_client", lambda: mock_client)

    stats = {"duration_sec": 300, "total_reps_completed": 20, "total_reps_target": 20, "avg_form_score": 90}
    result = generate_workout_summary(stats)

    assert result["is_fallback"] is False
    assert "Tremendous session" in result["summary"]
    assert len(result["wins"]) == 2
    assert len(result["improvements"]) == 1


def test_generate_workout_summary_fallback_on_malformed_json(monkeypatch):
    """When LLM returns invalid JSON or fails, fallback to local rule-based summary without crashing."""
    mock_client = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "I am an AI coach and you did a great job!"  # Non-JSON
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_client.messages.create.return_value = mock_response

    monkeypatch.setattr("services.coach_llm.get_anthropic_client", lambda: mock_client)

    stats = {"duration_sec": 300, "total_reps_completed": 20, "total_reps_target": 20, "avg_form_score": 90}
    result = generate_workout_summary(stats)

    assert result["is_fallback"] is True
    assert "summary" in result
    assert "wins" in result


def test_chat_input_length_limit():
    """Questions exceeding 500 characters must return HTTP 400 error."""
    long_question = "A" * 501
    res = chat_with_coach(long_question)
    assert res["status"] == 400
    assert "maximum length of 500" in res["error"]

    empty_res = chat_with_coach("   ")
    assert empty_res["status"] == 400
    assert "cannot be empty" in empty_res["error"]


def test_chat_rate_limiting():
    """Verify rate limiter triggers HTTP 429 when max requests are exceeded."""
    limiter = SimpleRateLimiter(max_requests=3, window_sec=60)
    client_ip = "192.168.1.100"

    assert limiter.is_allowed(client_ip)[0] is True
    assert limiter.is_allowed(client_ip)[0] is True
    assert limiter.is_allowed(client_ip)[0] is True

    allowed, retry_after = limiter.is_allowed(client_ip)
    assert allowed is False
    assert retry_after > 0


def test_chat_with_mocked_claude_response(monkeypatch):
    """Verify chat handles conversation with mocked Anthropic client."""
    mock_client = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "To fix forward knee drift on squats, keep your weight centered across your midfoot."
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_client.messages.create.return_value = mock_response

    monkeypatch.setattr("services.coach_llm.get_anthropic_client", lambda: mock_client)

    res = chat_with_coach("How do I stop my knees from drifting forward?", client_ip="10.0.0.1")
    assert res["status"] == 200
    assert "midfoot" in res["response"]
