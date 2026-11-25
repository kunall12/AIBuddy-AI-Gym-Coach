"""Unit tests for workout state machine transitions and session tracker."""

import pytest
from core.session_tracker import WorkoutRunner, WorkoutState, SessionTracker
from services.workout_plans import get_all_plans, get_plan_by_id, get_supported_goals


def test_supported_plans_exist_and_use_supported_detectors():
    """Verify standard goals exist and only contain supported exercises."""
    goals = get_supported_goals()
    assert "Fat Loss" in goals
    assert "Strength" in goals
    assert "Beginner" in goals

    supported_exercises = {
        "Squats",
        "Push-ups",
        "Biceps Curls (Dumbbell)",
        "Shoulder Press",
        "Lunges",
    }

    all_plans = get_all_plans()
    for plan_id, plan in all_plans.items():
        assert len(plan["exercises"]) > 0
        for ex in plan["exercises"]:
            assert ex["exercise_name"] in supported_exercises, (
                f"Exercise '{ex['exercise_name']}' in plan '{plan_id}' is not in supported detectors!"
            )
            assert ex["sets"] > 0
            assert ex["reps"] > 0
            assert ex["rest_seconds"] >= 0


def test_state_machine_initialization_and_start():
    """Test transitions: PLAN_SELECTED -> EXERCISE."""
    plan = {
        "id": "test_plan",
        "goal": "Test",
        "exercises": [
            {"exercise_name": "Squats", "sets": 2, "reps": 5, "rest_seconds": 10, "form_cue": "Chest up"},
            {"exercise_name": "Push-ups", "sets": 1, "reps": 5, "rest_seconds": 10, "form_cue": "Straight plank"},
        ],
    }
    runner = WorkoutRunner(plan)
    assert runner.state == WorkoutState.PLAN_SELECTED

    runner.start_workout()
    assert runner.state == WorkoutState.EXERCISE
    assert runner.current_exercise["exercise_name"] == "Squats"
    assert runner.current_set_idx == 1
    assert runner.current_reps == 0
    assert runner.target_reps == 5

    cues = runner.pop_voice_cues()
    assert len(cues) > 0
    assert "Squats" in cues[0]


def test_auto_advance_set_to_rest_and_next_set():
    """Verify auto-advancement to REST when target reps are met, then to next set."""
    plan = {
        "id": "test_plan",
        "exercises": [
            {"exercise_name": "Squats", "sets": 2, "reps": 3, "rest_seconds": 5},
            {"exercise_name": "Push-ups", "sets": 1, "reps": 3, "rest_seconds": 5},
        ],
    }
    runner = WorkoutRunner(plan)
    runner.start_workout()

    # Simulate 3 reps completed
    runner.update_reps_from_detector(1)
    runner.update_reps_from_detector(2)
    assert runner.current_reps == 2
    assert runner.state == WorkoutState.EXERCISE

    # 3rd rep completes set -> enters REST
    runner.update_reps_from_detector(3)
    assert runner.state == WorkoutState.REST
    assert runner.rest_seconds_remaining == 5.0
    cues = runner.pop_voice_cues()
    assert any("Rest, 5 seconds" in c for c in cues)

    # Rest countdown
    runner.tick_rest(dt=2.0)
    assert runner.rest_seconds_remaining == 3.0
    # 3-2-1 countdown cue
    runner.tick_rest(dt=0.1)
    cues = runner.pop_voice_cues()
    assert "Three" in cues

    # Finish rest timer -> starts Set 2
    runner.tick_rest(dt=3.0)
    assert runner.state == WorkoutState.EXERCISE
    assert runner.current_set_idx == 2
    assert runner.current_reps == 0


def test_exercise_transition_and_complete():
    """Verify moving from Exercise 1 to Exercise 2 to COMPLETE."""
    plan = {
        "id": "mini_plan",
        "exercises": [
            {"exercise_name": "Squats", "sets": 1, "reps": 2, "rest_seconds": 4},
            {"exercise_name": "Push-ups", "sets": 1, "reps": 2, "rest_seconds": 4},
        ],
    }
    runner = WorkoutRunner(plan)
    runner.start_workout()

    # Finish Squats
    runner.update_reps_from_detector(1)
    runner.update_reps_from_detector(2)
    assert runner.state == WorkoutState.REST
    assert "Push-ups" in runner.get_up_next_preview()

    # Skip rest to go to next exercise immediately
    runner.skip()
    assert runner.state == WorkoutState.EXERCISE
    assert runner.current_exercise["exercise_name"] == "Push-ups"
    assert runner.current_set_idx == 1

    # Finish Push-ups
    runner.update_reps_from_detector(3)
    runner.update_reps_from_detector(4)
    assert runner.state == WorkoutState.COMPLETE

    stats = runner.tracker.get_compact_stats()
    assert stats["total_reps_completed"] == 4
    assert stats["completion_rate_pct"] == 100.0
    assert len(stats["exercises"]) == 2


def test_pause_resume_skip_and_end_early():
    """Verify pause/resume controls and early exit."""
    plan = {
        "id": "test_plan",
        "exercises": [
            {"exercise_name": "Squats", "sets": 3, "reps": 10, "rest_seconds": 30},
        ],
    }
    runner = WorkoutRunner(plan)
    runner.start_workout()

    # Pause
    runner.pause()
    assert runner.state == WorkoutState.PAUSED
    assert runner.is_paused is True

    # While paused, rep updates should be ignored
    runner.update_reps_from_detector(1)
    assert runner.current_reps == 0

    # Resume
    runner.resume()
    assert runner.state == WorkoutState.EXERCISE
    assert runner.is_paused is False

    # Skip current set
    runner.skip()
    assert runner.state == WorkoutState.REST

    # End workout early
    runner.end_workout()
    assert runner.state == WorkoutState.COMPLETE
