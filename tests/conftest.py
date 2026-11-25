"""Pytest fixtures and configuration for AIBuddy tests.
Ensures tests run isolated without network or webcam dependencies.
"""

import os
import sys
from pathlib import Path
import pytest

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """Isolate environment variables and data storage for each test."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-mock-key")
    monkeypatch.setenv("COACH_MODEL", "claude-3-7-sonnet-latest")

    # Use temporary directory for progression file during tests
    temp_progression_file = tmp_path / "progression.json"
    import services.adaptive as adaptive_mod
    monkeypatch.setattr(adaptive_mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(adaptive_mod, "_PROGRESSION_FILE", temp_progression_file)

    yield
