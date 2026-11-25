"""Workout state machine and session metrics tracker for AIBuddy Guided Coaching.

Decoupled from camera capture, OpenCV, and WebRTC to enable standalone
unit-testing without hardware dependencies.
"""

from enum import Enum
import time
from typing import Any, Dict, List, Optional


class WorkoutState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PLAN_SELECTED = "PLAN_SELECTED"
    WARMUP = "WARMUP"
    EXERCISE = "EXERCISE"
    REST = "REST"
    NEXT_EXERCISE = "NEXT_EXERCISE"
    PAUSED = "PAUSED"
    COMPLETE = "COMPLETE"


class SessionTracker:
    """Tracks per-rep metrics, tempos, form errors, rest periods, and fatigue indicators."""

    def __init__(self):
        self.session_start_time = time.time()
        self.session_end_time: Optional[float] = None
        self.exercises_data: List[Dict[str, Any]] = []
        self._current_exercise_name: Optional[str] = None
        self._current_set_idx: int = 1
        self._set_start_time: float = time.time()
        self._last_rep_time: float = time.time()
        self._current_set_reps: List[Dict[str, Any]] = []
        self._rest_start_time: Optional[float] = None
        self._rest_durations: List[float] = []

    def start_exercise(self, exercise_name: str, target_sets: int, target_reps: int):
        self._current_exercise_name = exercise_name
        self._current_set_idx = 1
        self._set_start_time = time.time()
        self._last_rep_time = self._set_start_time
        self._current_set_reps = []

    def start_set(self, set_idx: int, target_reps: int):
        self._current_set_idx = set_idx
        self._set_start_time = time.time()
        self._last_rep_time = self._set_start_time
        self._current_set_reps = []

    def record_rep(
        self,
        rep_number: int,
        metrics: Optional[Dict[str, Any]] = None,
        form_score: float = 100.0,
        flagged_errors: Optional[List[str]] = None,
    ):
        now = time.time()
        rep_duration = max(0.2, now - self._last_rep_time)
        self._last_rep_time = now

        rep_record = {
            "rep_number": rep_number,
            "timestamp": now,
            "tempo_sec": round(rep_duration, 2),
            "form_score": round(form_score, 1),
            "flagged_errors": list(flagged_errors or []),
            "metrics": dict(metrics or {}),
        }
        self._current_set_reps.append(rep_record)
        return rep_record

    def end_set(self, target_reps: int, completed_reps: int, rest_target: int):
        now = time.time()
        set_duration = max(0.5, now - self._set_start_time)

        # Calculate average tempo and form quality
        tempos = [r["tempo_sec"] for r in self._current_set_reps]
        avg_tempo = round(sum(tempos) / len(tempos), 2) if tempos else 0.0

        scores = [r["form_score"] for r in self._current_set_reps]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 100.0

        all_errors: List[str] = []
        for r in self._current_set_reps:
            all_errors.extend(r["flagged_errors"])

        set_summary = {
            "exercise": self._current_exercise_name,
            "set_number": self._current_set_idx,
            "target_reps": target_reps,
            "completed_reps": completed_reps,
            "duration_sec": round(set_duration, 1),
            "avg_tempo_sec": avg_tempo,
            "avg_form_score": avg_score,
            "flagged_errors": all_errors,
            "reps_detail": list(self._current_set_reps),
        }
        self.exercises_data.append(set_summary)
        self._current_set_reps = []
        self._rest_start_time = now

    def end_rest(self):
        if self._rest_start_time:
            actual_rest = round(time.time() - self._rest_start_time, 1)
            self._rest_durations.append(actual_rest)
            self._rest_start_time = None

    def end_session(self):
        self.session_end_time = time.time()

    def get_compact_stats(self) -> Dict[str, Any]:
        """Produce a structured, compact JSON-serializable dictionary of session stats."""
        total_time = (
            round((self.session_end_time or time.time()) - self.session_start_time, 1)
        )

        total_reps_completed = sum(s.get("completed_reps", 0) for s in self.exercises_data)
        total_reps_target = sum(s.get("target_reps", 0) for s in self.exercises_data)

        # Aggregate by exercise
        exercise_aggregates: Dict[str, Dict[str, Any]] = {}
        for s in self.exercises_data:
            name = s.get("exercise", "Unknown")
            if name not in exercise_aggregates:
                exercise_aggregates[name] = {
                    "sets_completed": 0,
                    "target_sets": 0,
                    "reps_completed": 0,
                    "target_reps": 0,
                    "form_scores": [],
                    "errors": [],
                    "tempos": [],
                }
            agg = exercise_aggregates[name]
            agg["sets_completed"] += 1
            agg["reps_completed"] += s.get("completed_reps", 0)
            agg["target_reps"] += s.get("target_reps", 0)
            agg["form_scores"].append(s.get("avg_form_score", 100))
            agg["errors"].extend(s.get("flagged_errors", []))
            if s.get("avg_tempo_sec", 0) > 0:
                agg["tempos"].append(s["avg_tempo_sec"])

        exercise_summaries = []
        for name, agg in exercise_aggregates.items():
            mean_score = (
                round(sum(agg["form_scores"]) / len(agg["form_scores"]), 1)
                if agg["form_scores"]
                else 100.0
            )
            mean_tempo = (
                round(sum(agg["tempos"]) / len(agg["tempos"]), 2)
                if agg["tempos"]
                else 0.0
            )
            # Find most common errors
            err_counts: Dict[str, int] = {}
            for err in agg["errors"]:
                err_counts[err] = err_counts.get(err, 0) + 1
            top_errors = sorted(err_counts.items(), key=lambda x: x[1], reverse=True)[:3]

            exercise_summaries.append(
                {
                    "exercise": name,
                    "sets_completed": agg["sets_completed"],
                    "reps_completed": agg["reps_completed"],
                    "target_reps": agg["target_reps"],
                    "avg_form_score": mean_score,
                    "avg_tempo_sec": mean_tempo,
                    "common_errors": [e[0] for e in top_errors],
                }
            )

        avg_session_score = (
            round(
                sum(s.get("avg_form_score", 100) for s in self.exercises_data)
                / max(1, len(self.exercises_data)),
                1,
            )
        )

        return {
            "duration_sec": total_time,
            "total_reps_completed": total_reps_completed,
            "total_reps_target": total_reps_target,
            "completion_rate_pct": round(
                (total_reps_completed / max(1, total_reps_target)) * 100, 1
            ),
            "avg_form_score": avg_session_score,
            "sets_data": self.exercises_data,
            "exercises": exercise_summaries,
            "rest_durations_sec": self._rest_durations,
        }


class WorkoutRunner:
    """State machine governing a guided workout routine."""

    def __init__(self, plan: Dict[str, Any]):
        self.plan = plan
        self.exercises: List[Dict[str, Any]] = list(plan.get("exercises", []))
        self.state: WorkoutState = WorkoutState.PLAN_SELECTED

        self.current_exercise_idx: int = 0
        self.current_set_idx: int = 1
        self.current_reps: int = 0
        self.target_reps: int = (
            self.exercises[0]["reps"] if self.exercises else 10
        )

        self.rest_seconds_total: int = 30
        self.rest_seconds_remaining: float = 0.0
        self._rest_start_timestamp: float = 0.0

        self.is_paused: bool = False
        self._pause_state: Optional[WorkoutState] = None

        self.tracker: SessionTracker = SessionTracker()
        self.voice_queue: List[str] = []
        self._last_announced_countdown: Optional[int] = None
        self._initial_detector_baseline: int = 0
        self._last_seen_detector_reps: int = 0

    @property
    def current_exercise(self) -> Optional[Dict[str, Any]]:
        if 0 <= self.current_exercise_idx < len(self.exercises):
            return self.exercises[self.current_exercise_idx]
        return None

    @property
    def total_sets_in_workout(self) -> int:
        return sum(ex.get("sets", 1) for ex in self.exercises)

    @property
    def completed_sets_count(self) -> int:
        count = 0
        for i in range(self.current_exercise_idx):
            count += self.exercises[i].get("sets", 1)
        count += max(0, self.current_set_idx - 1)
        return count

    @property
    def overall_progress_fraction(self) -> float:
        total = self.total_sets_in_workout
        if total == 0:
            return 1.0
        return min(1.0, self.completed_sets_count / total)

    def start_workout(self):
        """Start the workout, moving into EXERCISE state."""
        if not self.exercises:
            self.state = WorkoutState.COMPLETE
            return

        self.current_exercise_idx = 0
        self.current_set_idx = 1
        self.current_reps = 0
        self.target_reps = self.exercises[0].get("reps", 10)
        self.state = WorkoutState.EXERCISE
        self.is_paused = False

        ex = self.current_exercise
        self.tracker.start_exercise(ex["exercise_name"], ex["sets"], self.target_reps)
        cue = f"Starting {ex['exercise_name']}. Set 1 of {ex['sets']}. Target {self.target_reps} reps. {ex.get('form_cue', '')}"
        self.voice_queue.append(cue.strip())

    def pause(self):
        """Pause the current workout."""
        if self.state not in (WorkoutState.COMPLETE, WorkoutState.PAUSED):
            self._pause_state = self.state
            self.state = WorkoutState.PAUSED
            self.is_paused = True

    def resume(self):
        """Resume a paused workout."""
        if self.state == WorkoutState.PAUSED:
            self.state = self._pause_state or WorkoutState.EXERCISE
            self.is_paused = False
            self._pause_state = None

    def skip(self):
        """Skip current rest countdown OR advance set/exercise."""
        if self.state == WorkoutState.REST:
            self._finish_rest()
        elif self.state == WorkoutState.EXERCISE:
            self._complete_current_set(completed_reps=self.current_reps)

    def end_workout(self):
        """End the workout immediately and mark COMPLETE."""
        self.state = WorkoutState.COMPLETE
        self.tracker.end_session()
        self.voice_queue.append("Workout ended. Outstanding effort! Let's check your results.")

    def update_reps_from_detector(
        self,
        detector_reps: int,
        metrics: Optional[Dict[str, Any]] = None,
        form_score: float = 100.0,
        flagged_errors: Optional[List[str]] = None,
    ):
        """Update rep counter based on detector stream."""
        if self.state != WorkoutState.EXERCISE or self.is_paused:
            return

        # Track delta from previous detector observation
        if self._last_seen_detector_reps == 0 and detector_reps > 0:
            self._initial_detector_baseline = detector_reps - 1

        delta = detector_reps - self._last_seen_detector_reps
        self._last_seen_detector_reps = detector_reps

        if delta > 0:
            for _ in range(delta):
                self.current_reps += 1
                self.tracker.record_rep(
                    rep_number=self.current_reps,
                    metrics=metrics,
                    form_score=form_score,
                    flagged_errors=flagged_errors,
                )

                if self.current_reps >= self.target_reps:
                    self._complete_current_set(completed_reps=self.current_reps)
                    break

    def _complete_current_set(self, completed_reps: int):
        ex = self.current_exercise
        if not ex:
            self.state = WorkoutState.COMPLETE
            return

        self.tracker.end_set(
            target_reps=self.target_reps,
            completed_reps=completed_reps,
            rest_target=ex.get("rest_seconds", 30),
        )

        total_sets = ex.get("sets", 1)
        if self.current_set_idx < total_sets:
            # More sets remaining in this exercise -> REST
            self._start_rest(
                rest_seconds=ex.get("rest_seconds", 30),
                next_desc=f"Set {self.current_set_idx + 1} of {ex['exercise_name']}",
            )
        else:
            # Exercise finished. Check next exercise.
            if self.current_exercise_idx + 1 < len(self.exercises):
                next_ex = self.exercises[self.current_exercise_idx + 1]
                self._start_rest(
                    rest_seconds=ex.get("rest_seconds", 30),
                    next_desc=f"{next_ex['exercise_name']}, {next_ex.get('sets', 1)} sets of {next_ex.get('reps', 10)} reps",
                    is_next_exercise=True,
                )
            else:
                # All exercises completed!
                self.state = WorkoutState.COMPLETE
                self.tracker.end_session()
                self.voice_queue.append("Workout complete! Fantastic work finishing your entire routine.")

    def _start_rest(self, rest_seconds: int, next_desc: str, is_next_exercise: bool = False):
        self.state = WorkoutState.REST
        self.rest_seconds_total = rest_seconds
        self.rest_seconds_remaining = float(rest_seconds)
        self._rest_start_timestamp = time.time()
        self._last_announced_countdown = None
        self._is_transitioning_exercise = is_next_exercise

        announcement = f"Rest, {rest_seconds} seconds. Next up: {next_desc}."
        self.voice_queue.append(announcement)

    def tick_rest(self, dt: float = 0.5):
        """Advance the rest timer by dt seconds; fires audio countdown cues."""
        if self.state != WorkoutState.REST or self.is_paused:
            return

        self.rest_seconds_remaining = max(0.0, self.rest_seconds_remaining - dt)
        rem_int = int(round(self.rest_seconds_remaining))

        # 3-2-1 Countdown cues
        if 1 <= rem_int <= 3 and rem_int != self._last_announced_countdown:
            self._last_announced_countdown = rem_int
            words = {3: "Three", 2: "Two", 1: "One"}
            self.voice_queue.append(words[rem_int])

        if self.rest_seconds_remaining <= 0.0:
            self._finish_rest()

    def _finish_rest(self):
        self.tracker.end_rest()
        ex = self.current_exercise
        if not ex:
            self.state = WorkoutState.COMPLETE
            return

        if getattr(self, "_is_transitioning_exercise", False):
            self.current_exercise_idx += 1
            self.current_set_idx = 1
            ex = self.current_exercise
            if not ex:
                self.state = WorkoutState.COMPLETE
                return
            self.target_reps = ex.get("reps", 10)
            self.tracker.start_exercise(ex["exercise_name"], ex["sets"], self.target_reps)
        else:
            self.current_set_idx += 1
            self.tracker.start_set(self.current_set_idx, self.target_reps)

        self.current_reps = 0
        self.state = WorkoutState.EXERCISE
        self._is_transitioning_exercise = False
        cue = f"Set {self.current_set_idx}. Let's go!"
        self.voice_queue.append(cue)

    def pop_voice_cues(self) -> List[str]:
        """Retrieve and clear pending voice cues."""
        cues = list(self.voice_queue)
        self.voice_queue.clear()
        return cues

    def get_up_next_preview(self) -> str:
        """Returns concise description of the upcoming set or exercise."""
        ex = self.current_exercise
        if not ex:
            return "Routine Complete"

        if self.current_set_idx < ex.get("sets", 1):
            return f"{ex['exercise_name']} — Set {self.current_set_idx + 1} of {ex['sets']}"
        elif self.current_exercise_idx + 1 < len(self.exercises):
            next_ex = self.exercises[self.current_exercise_idx + 1]
            return f"{next_ex['exercise_name']} — {next_ex.get('sets', 1)} sets × {next_ex.get('reps', 10)} reps"
        else:
            return "Finish Workout"

    def get_ui_state(self) -> Dict[str, Any]:
        """Provides full snapshot for UI rendering."""
        ex = self.current_exercise or {}
        return {
            "state": self.state.value,
            "exercise_name": ex.get("exercise_name", "None"),
            "current_set": self.current_set_idx,
            "target_sets": ex.get("sets", 1),
            "current_reps": self.current_reps,
            "target_reps": self.target_reps,
            "form_cue": ex.get("form_cue", ""),
            "rest_remaining": int(round(self.rest_seconds_remaining)),
            "rest_total": self.rest_seconds_total,
            "up_next": self.get_up_next_preview(),
            "overall_progress": round(self.overall_progress_fraction, 2),
            "is_paused": self.is_paused,
            "completed_sets": self.completed_sets_count,
            "total_sets": self.total_sets_in_workout,
        }
