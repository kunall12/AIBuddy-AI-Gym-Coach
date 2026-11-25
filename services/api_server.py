"""Tornado HTTP endpoints for POST /api/coach/summary and POST /api/coach/chat.

Integrates with Streamlit's underlying Tornado web server and supports standalone
instantiation for unit testing with pytest / tornado.testing.
"""

import gc
import json
from typing import Any
import tornado.web

from services.coach_llm import generate_workout_summary, chat_with_coach


class BaseCoachHandler(tornado.web.RequestHandler):
    """Base handler with CORS headers and JSON utilities."""

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.set_header("Access-Control-Allow-Methods", "POST, OPTIONS, GET")
        self.set_header("Content-Type", "application/json")

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def get_json_body(self) -> dict:
        try:
            raw = self.request.body.decode("utf-8") if self.request.body else "{}"
            return json.loads(raw)
        except Exception:
            return {}


class CoachSummaryHandler(BaseCoachHandler):
    """POST /api/coach/summary: Generates personalized post-session summary via Claude API."""

    def post(self):
        body = self.get_json_body()
        summary_result = generate_workout_summary(body)
        self.set_status(200)
        self.write(json.dumps(summary_result))


class CoachChatHandler(BaseCoachHandler):
    """POST /api/coach/chat: Interactive chat endpoint with safeguards and rate limiting."""

    def post(self):
        body = self.get_json_body()
        question = body.get("question", "")
        session_stats = body.get("session_stats", {})
        history = body.get("history", [])

        # Detect remote IP
        forwarded = self.request.headers.get("X-Forwarded-For")
        client_ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (self.request.remote_ip or "127.0.0.1")
        )

        result = chat_with_coach(
            question=question,
            session_stats=session_stats,
            history=history,
            client_ip=client_ip,
        )

        status_code = result.get("status", 200)
        self.set_status(status_code)
        self.write(json.dumps(result))


def ensure_api_routes(app: tornado.web.Application):
    """Attach coach endpoints to a Tornado application instance if not already present."""
    handlers = getattr(app, "handlers", None)
    if handlers:
        for host_spec, routes in handlers:
            for route in routes:
                if hasattr(route, "regex") and "/api/coach" in getattr(route.regex, "pattern", ""):
                    return

    app.add_handlers(
        r".*",
        [
            (r"/api/coach/summary", CoachSummaryHandler),
            (r"/api/coach/chat", CoachChatHandler),
        ],
    )


def attach_routes_to_streamlit_server() -> bool:
    """Locate the running Streamlit Tornado server and attach the coach API handlers."""
    attached = False
    for obj in gc.get_objects():
        if isinstance(obj, tornado.web.Application):
            try:
                ensure_api_routes(obj)
                attached = True
            except Exception as exc:
                print(f"[ApiServer] Could not attach routes: {exc}")
    return attached
