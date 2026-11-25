"""Integration tests for Tornado endpoints POST /api/coach/summary and POST /api/coach/chat."""

import json
from unittest.mock import MagicMock
import tornado.web
from tornado.testing import AsyncHTTPTestCase

from services.api_server import CoachSummaryHandler, CoachChatHandler


class TestCoachApiEndpoints(AsyncHTTPTestCase):
    def get_app(self):
        return tornado.web.Application(
            [
                (r"/api/coach/summary", CoachSummaryHandler),
                (r"/api/coach/chat", CoachChatHandler),
            ]
        )

    def test_summary_endpoint_post_success(self):
        """POST /api/coach/summary should return 200 with structured JSON."""
        from unittest.mock import patch
        mock_summary = {
            "summary": "Great workout!",
            "wins": ["Completed all sets"],
            "improvements": ["Control tempo"],
            "tips": ["Hydrate properly"],
            "next_session": ["Add 2 reps"],
            "is_fallback": False,
        }
        with patch("services.api_server.generate_workout_summary", return_value=mock_summary):
            payload = {
                "duration_sec": 480,
                "total_reps_completed": 30,
                "total_reps_target": 30,
                "avg_form_score": 92.0,
                "exercises": [{"exercise": "Squats", "reps_completed": 30}],
            }
            response = self.fetch(
                "/api/coach/summary",
                method="POST",
                body=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
            assert response.code == 200
            data = json.loads(response.body.decode("utf-8"))
            assert "summary" in data
            assert "wins" in data
            assert "improvements" in data
            assert "tips" in data
            assert "next_session" in data
            assert response.headers.get("Access-Control-Allow-Origin") == "*"

    def test_chat_endpoint_post_empty_question(self):
        """POST /api/coach/chat with empty question returns HTTP 400."""
        payload = {"question": "   "}
        response = self.fetch(
            "/api/coach/chat",
            method="POST",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert response.code == 400
        data = json.loads(response.body.decode("utf-8"))
        assert "error" in data

    def test_chat_endpoint_post_too_long_question(self):
        """POST /api/coach/chat with question > 500 chars returns HTTP 400."""
        payload = {"question": "X" * 501}
        response = self.fetch(
            "/api/coach/chat",
            method="POST",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert response.code == 400
        data = json.loads(response.body.decode("utf-8"))
        assert "maximum length of 500" in data["error"]

    def test_chat_endpoint_cors_options(self):
        """OPTIONS preflight should return 204 with CORS headers."""
        response = self.fetch("/api/coach/chat", method="OPTIONS")
        assert response.code == 204
        assert response.headers.get("Access-Control-Allow-Origin") == "*"
