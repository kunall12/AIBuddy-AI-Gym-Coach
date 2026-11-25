"""Unit tests for adaptive difficulty decision function and progression persistence."""

import pytest
from services.adaptive import (
    evaluate_set_performance,
    AdaptiveAction,
    calculate_rep_form_score,
    save_exercise_progression,
    load_exercise_progression,
)


def test_calculate_rep_form_score_various_exercises():
    """Verify form scores reflect detector issues across exercises."""
    # Good squat
    score_good = calculate_rep_form_score({"depth_status": "GOOD DEPTH", "back_angle": 160}, "Squats")
    assert score_good == 100.0

    # Squat too high and forward lean
    score_bad_squat = calculate_rep_form_score({"depth_status": "TOO HIGH", "back_angle": 120}, "Squats")
    assert score_bad_squat == 45.0

    # Push-up sagging
    score_bad_pushup = calculate_rep_form_score({"body_alignment": "Poor Form", "hip_status": "SAGGING"}, "Push-ups")
    assert score_bad_pushup == 40.0

    # Biceps curl swinging
    score_swinging = calculate_rep_form_score({"swing_status": "SWINGING", "shoulder_status": "STABLE"}, "Biceps Curls (Dumbbell)")
    assert score_swinging == 65.0


def test_good_set_in_progress_continues():
    """Steady form and tempo while working toward target returns CONTINUE."""
    rep_records = [
        {"rep_number": 1, "tempo_sec": 2.0, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 2, "tempo_sec": 2.1, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 3, "tempo_sec": 2.0, "form_score": 90.0, "flagged_errors": []},
        {"rep_number": 4, "tempo_sec": 2.1, "form_score": 95.0, "flagged_errors": []},
    ]
    dec = evaluate_set_performance(rep_records, target_reps=10, exercise_name="Squats")
    assert dec.action == AdaptiveAction.CONTINUE
    assert dec.new_target == 10


def test_easy_finish_suggests_increase():
    """Completing all target reps with high form score and stable tempo suggests increase."""
    rep_records = [
        {"rep_number": 1, "tempo_sec": 1.8, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 2, "tempo_sec": 1.8, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 3, "tempo_sec": 1.9, "form_score": 90.0, "flagged_errors": []},
        {"rep_number": 4, "tempo_sec": 1.9, "form_score": 90.0, "flagged_errors": []},
        {"rep_number": 5, "tempo_sec": 2.0, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 6, "tempo_sec": 2.0, "form_score": 90.0, "flagged_errors": []},
    ]
    dec = evaluate_set_performance(rep_records, target_reps=6, exercise_name="Squats")
    assert dec.action == AdaptiveAction.SUGGEST_INCREASE
    assert dec.new_target == 8  # Increased by 2
    assert "level up" in dec.reason.lower() or "clean finish" in dec.reason.lower()


def test_late_form_drop_suggests_lowering_target():
    """Early baseline is solid (95), but last reps form degrades significantly (>20%)."""
    rep_records = [
        {"rep_number": 1, "tempo_sec": 1.8, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 2, "tempo_sec": 1.9, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 3, "tempo_sec": 1.8, "form_score": 90.0, "flagged_errors": []},
        {"rep_number": 4, "tempo_sec": 2.4, "form_score": 60.0, "flagged_errors": ["Knees caving"]},
        {"rep_number": 5, "tempo_sec": 2.8, "form_score": 55.0, "flagged_errors": ["Too high depth"]},
    ]
    dec = evaluate_set_performance(rep_records, target_reps=10, exercise_name="Squats")
    assert dec.action in (AdaptiveAction.SUGGEST_LOWER, AdaptiveAction.SUGGEST_STOP)
    assert dec.new_target <= 8
    assert "form" in dec.reason.lower()


def test_severe_form_breakdown_and_slowing_tempo_suggests_stop():
    """Drastic drop in score (>30%) coupled with slow tempo suggests stopping the set."""
    rep_records = [
        {"rep_number": 1, "tempo_sec": 1.5, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 2, "tempo_sec": 1.6, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 3, "tempo_sec": 1.6, "form_score": 95.0, "flagged_errors": []},
        {"rep_number": 4, "tempo_sec": 3.5, "form_score": 45.0, "flagged_errors": ["Hips sagging", "Poor form"]},
        {"rep_number": 5, "tempo_sec": 4.0, "form_score": 40.0, "flagged_errors": ["Hips sagging", "Poor form"]},
    ]
    dec = evaluate_set_performance(rep_records, target_reps=10, exercise_name="Push-ups")
    assert dec.action == AdaptiveAction.SUGGEST_STOP
    assert dec.new_target == 5
    assert "stop" in dec.reason.lower() or "paus" in dec.reason.lower()


def test_noisy_and_empty_data_handled_gracefully():
    """Handles empty lists, None values, and zero reps without raising errors."""
    dec_empty = evaluate_set_performance([], target_reps=10)
    assert dec_empty.action == AdaptiveAction.CONTINUE

    dec_single = evaluate_set_performance(
        [{"rep_number": 1, "tempo_sec": None, "form_score": 80.0, "flagged_errors": None}],
        target_reps=10,
    )
    assert dec_single.action == AdaptiveAction.CONTINUE


def test_progression_persistence():
    """Verify local saving and loading of exercise progression data."""
    save_exercise_progression(
        exercise_name="Shoulder Press",
        suggested_target_reps=12,
        reason="Consistent full extension achieved on all sets.",
        weight_suggestion="+2.5 kg next session",
    )

    loaded = load_exercise_progression("Shoulder Press")
    assert loaded is not None
    assert loaded["suggested_target_reps"] == 12
    assert loaded["weight_suggestion"] == "+2.5 kg next session"
