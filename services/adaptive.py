"""Adaptive difficulty engine and local progression persistence for AIBuddy.

Monitors per-rep form metrics and tempo within sets to detect fatigue,
form drops, and easy finishes. Persists progression adjustments locally
to data/progression.json for subsequent workout sessions.

Pure, deterministic logic decoupled from camera and UI for unit testing.
"""

from dataclasses import dataclass, asdict
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# ADAPTIVE CONFIGURATION THRESHOLDS
# ============================================================================
EARLY_BASELINE_REPS: int = 3           # Reps used to establish baseline tempo and form score
FORM_DROP_THRESHOLD_PCT: float = 20.0  # Percentage drop in form score below early baseline
TEMPO_SLOWDOWN_FACTOR: float = 1.45    # Multiplier on baseline tempo that signifies severe fatigue
CONSECUTIVE_ERRORS_FOR_DROP: int = 2   # Number of consecutive reps with flagged errors
EASY_FINISH_MIN_SCORE: float = 85.0    # Minimum average form score required for progression increase
EASY_FINISH_MAX_TEMPO_DRIFT: float = 0.35  # Maximum tempo elongation permitted for easy finish
MIN_REPS_FOR_MIDSET_CHECK: int = 4     # Do not trigger fatigue warnings before this rep count


class AdaptiveAction(str, Enum):
    CONTINUE = "continue"
    SUGGEST_STOP = "suggest_stop"
    SUGGEST_LOWER = "suggest_lower"
    SUGGEST_INCREASE = "suggest_increase"


@dataclass
class AdaptiveDecision:
    action: AdaptiveAction
    reason: str
    new_target: Optional[int] = None
    voice_cue: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "new_target": self.new_target,
            "voice_cue": self.voice_cue,
        }


def calculate_rep_form_score(metrics: Optional[Dict[str, Any]], exercise_name: str) -> float:
    """Derive a 0-100 numerical form quality score from raw detector metrics."""
    if not metrics:
        return 80.0

    score = 100.0
    ex = exercise_name.lower()

    if "squat" in ex:
        depth = metrics.get("depth_status", "")
        back = metrics.get("back_angle", 180)
        if depth == "TOO HIGH":
            score -= 30.0
        if isinstance(back, (int, float)) and back < 130:
            score -= 25.0

    elif "push" in ex:
        alignment = metrics.get("body_alignment", "")
        hip = metrics.get("hip_status", "")
        if alignment == "Poor Form":
            score -= 35.0
        elif alignment == "Slight Bend":
            score -= 15.0
        if hip in ("SAGGING", "PIKED UP"):
            score -= 25.0

    elif "curl" in ex:
        swing = metrics.get("swing_status", "")
        shoulder = metrics.get("shoulder_status", "")
        if swing == "SWINGING":
            score -= 35.0
        if shoulder == "ELBOW DRIFTING":
            score -= 25.0

    elif "press" in ex:
        arch = metrics.get("back_arch_status", "")
        ext = metrics.get("extension_status", "")
        if arch == "Excessive Arch":
            score -= 35.0
        elif arch == "Slight Arch":
            score -= 15.0
        if ext == "PRESSING":
            score -= 10.0

    elif "lunge" in ex:
        balance = metrics.get("balance_status", "")
        if balance == "OFF BALANCE":
            score -= 30.0

    return max(0.0, min(100.0, score))


def evaluate_set_performance(
    rep_records: List[Dict[str, Any]],
    target_reps: int,
    exercise_name: str = "Exercise",
) -> AdaptiveDecision:
    """Pure decision function evaluating live set performance and fatigue.

    Input:
      - rep_records: list of rep dicts with keys 'rep_number', 'tempo_sec', 'form_score', 'flagged_errors'
      - target_reps: target rep goal for current set
      - exercise_name: name of current exercise

    Output:
      - AdaptiveDecision: action (continue | suggest_stop | suggest_lower | suggest_increase), reason, new_target
    """
    if not rep_records or len(rep_records) == 0:
        return AdaptiveDecision(
            action=AdaptiveAction.CONTINUE,
            reason="Set just started; gathering movement baseline.",
            new_target=target_reps,
        )

    current_rep_count = len(rep_records)

    # 1. Easy finish check (when all target reps are completed)
    if current_rep_count >= target_reps:
        scores = [r.get("form_score", 100.0) for r in rep_records]
        avg_score = sum(scores) / len(scores) if scores else 100.0
        tempos = [r.get("tempo_sec", 1.0) for r in rep_records if r.get("tempo_sec", 0) > 0]

        tempo_drift = 0.0
        if len(tempos) >= 4:
            early_tempo = sum(tempos[:2]) / 2
            late_tempo = sum(tempos[-2:]) / 2
            if early_tempo > 0:
                tempo_drift = (late_tempo - early_tempo) / early_tempo

        if avg_score >= EASY_FINISH_MIN_SCORE and tempo_drift <= EASY_FINISH_MAX_TEMPO_DRIFT:
            suggested_reps = target_reps + (2 if target_reps < 15 else 3)
            return AdaptiveDecision(
                action=AdaptiveAction.SUGGEST_INCREASE,
                reason=(
                    f"Clean finish on all {target_reps} reps with {avg_score:.0f}% avg form. "
                    f"Ready to level up next session!"
                ),
                new_target=suggested_reps,
                voice_cue=f"Great set with strong form! Suggesting {suggested_reps} reps next time.",
            )
        else:
            return AdaptiveDecision(
                action=AdaptiveAction.CONTINUE,
                reason=f"Target reps achieved ({target_reps}). Maintain current targets.",
                new_target=target_reps,
            )

    # 2. Mid-set fatigue & form drop detection
    if current_rep_count < MIN_REPS_FOR_MIDSET_CHECK:
        return AdaptiveDecision(
            action=AdaptiveAction.CONTINUE,
            reason=f"Rep {current_rep_count}/{target_reps}. Form baseline establishing.",
            new_target=target_reps,
        )

    # Calculate early rep baseline
    baseline_window = min(EARLY_BASELINE_REPS, max(2, current_rep_count - 2))
    early_reps = rep_records[:baseline_window]
    late_reps = rep_records[baseline_window:]

    early_scores = [r.get("form_score", 100.0) for r in early_reps]
    early_avg_score = sum(early_scores) / len(early_scores) if early_scores else 100.0

    recent_window = rep_records[-min(3, len(rep_records)):]
    recent_scores = [r.get("form_score", 100.0) for r in recent_window]
    recent_avg_score = sum(recent_scores) / len(recent_scores) if recent_scores else 100.0

    score_drop_pct = (
        ((early_avg_score - recent_avg_score) / early_avg_score) * 100.0
        if early_avg_score > 0
        else 0.0
    )

    # Tempo analysis
    early_tempos = [r.get("tempo_sec", 1.0) for r in early_reps if r.get("tempo_sec", 0) > 0]
    recent_tempos = [r.get("tempo_sec", 1.0) for r in recent_window if r.get("tempo_sec", 0) > 0]
    early_avg_tempo = sum(early_tempos) / len(early_tempos) if early_tempos else 1.0
    recent_avg_tempo = sum(recent_tempos) / len(recent_tempos) if recent_tempos else 1.0

    tempo_slowdown = (
        (recent_avg_tempo / early_avg_tempo)
        if early_avg_tempo > 0
        else 1.0
    )

    # Consecutive error count in trailing reps
    trailing_error_count = sum(
        1 for r in recent_window if len(r.get("flagged_errors", [])) > 0
    )

    # Severe form breakdown -> Suggest stopping
    if score_drop_pct >= (FORM_DROP_THRESHOLD_PCT * 1.5) or (
        trailing_error_count >= CONSECUTIVE_ERRORS_FOR_DROP and tempo_slowdown >= TEMPO_SLOWDOWN_FACTOR
    ):
        return AdaptiveDecision(
            action=AdaptiveAction.SUGGEST_STOP,
            reason=(
                f"Form dropped by {score_drop_pct:.0f}% in recent reps with significant tempo slowing. "
                "Consider safely pausing this set to avoid injury."
            ),
            new_target=current_rep_count,
            voice_cue="Form is slipping. Consider stopping this set to stay safe.",
        )

    # Moderate form breakdown -> Suggest lowering rep target
    if score_drop_pct >= FORM_DROP_THRESHOLD_PCT or trailing_error_count >= CONSECUTIVE_ERRORS_FOR_DROP:
        suggested_target = max(current_rep_count, target_reps - 2)
        return AdaptiveDecision(
            action=AdaptiveAction.SUGGEST_LOWER,
            reason=(
                f"Form score slipped to {recent_avg_score:.0f}%. "
                f"Suggesting lowering target to {suggested_target} reps."
            ),
            new_target=suggested_target,
            voice_cue=f"Form is slipping slightly. Consider finishing this set at {suggested_target} reps.",
        )

    return AdaptiveDecision(
        action=AdaptiveAction.CONTINUE,
        reason=f"Rep {current_rep_count}/{target_reps}. Form and tempo stable.",
        new_target=target_reps,
    )


# ============================================================================
# PROGRESSION PERSISTENCE (data/progression.json)
# ============================================================================
_DATA_DIR = Path(__file__).parent.parent / "data"
_PROGRESSION_FILE = _DATA_DIR / "progression.json"


def _ensure_data_dir():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_all_progressions() -> Dict[str, Any]:
    """Load all saved exercise progression recommendations."""
    _ensure_data_dir()
    if not _PROGRESSION_FILE.exists():
        return {}
    try:
        with open(_PROGRESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_exercise_progression(exercise_name: str) -> Optional[Dict[str, Any]]:
    """Retrieve progression recommendations for a specific exercise."""
    progressions = load_all_progressions()
    return progressions.get(exercise_name)


def save_exercise_progression(
    exercise_name: str,
    suggested_target_reps: int,
    reason: str,
    weight_suggestion: Optional[str] = None,
):
    """Save an updated progression target for an exercise."""
    _ensure_data_dir()
    progressions = load_all_progressions()
    progressions[exercise_name] = {
        "exercise_name": exercise_name,
        "suggested_target_reps": suggested_target_reps,
        "reason": reason,
        "weight_suggestion": weight_suggestion or "Maintain current load",
        "updated_at": os.getenv("CURRENT_TIME", "") or str(Path.stat(_PROGRESSION_FILE).st_mtime if _PROGRESSION_FILE.exists() else ""),
    }
    with open(_PROGRESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(progressions, f, indent=2)
