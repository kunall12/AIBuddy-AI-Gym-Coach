
import time
import streamlit as st

from services.config.workout_config import METRICS_FIELDS
from services.persistence.exercise_repository import add_exercise


def _send_coach_event(event, exercise, metrics):
    """Call the voice pipeline and store any generated feedback."""

    pipeline = st.session_state.get("voice_pipeline")

    if pipeline is None:
        return False

    try:
        result = pipeline.process_event(
            event=event,
            exercise=exercise,
            metrics=metrics or {},
        )

        if result:
            audio, feedback = result

            st.session_state.audio_to_play = audio
            st.session_state.coach_feedback = feedback

            print(f"[Coach] Feedback generated for: {event}")
            return True

        return False

    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"

        print(f"[Coach] Event {event} failed: {message}")

        st.session_state.coach_feedback = (
            f"Coach error: {message}"
        )
        return False


def sync_metrics_update(context):
    """Synchronize video metrics, save completed sets, and coach the user."""

    if (
        context is None
        or not hasattr(context, "state")
        or not context.state.playing
    ):
        return

    processor = getattr(context, "video_processor", None)

    if processor is None:
        return

    exercise = st.session_state.get("exercise_type")

    if not exercise:
        return

    processor.set_exercise(exercise)

    latest_metrics = processor.get_latest_metrics()

    if not latest_metrics:
        return

    # ---------------- Rep count and exercise metrics ----------------
    try:
        reps = max(0, int(latest_metrics.get("reps", 0) or 0))
    except (TypeError, ValueError):
        reps = 0

    st.session_state.reps = reps

    fields = METRICS_FIELDS.get(exercise, {})

    for key, default in fields.items():
        st.session_state[key] = latest_metrics.get(key, default)

    # ---------------- Set progress ----------------
    reps_per_set = int(st.session_state.get("reps_per_set", 0) or 0)
    target_sets = int(st.session_state.get("target_sets", 0) or 0)

    if reps_per_set <= 0 or target_sets <= 0:
        st.session_state.sets_completed = 0
        st.session_state.current_set_reps = reps
        st.session_state.workout_completed = False
        return

    sets_completed = min(reps // reps_per_set, target_sets)
    current_set_reps = reps % reps_per_set
    workout_completed = reps >= reps_per_set * target_sets

    st.session_state.sets_completed = sets_completed
    st.session_state.current_set_reps = current_set_reps
    st.session_state.workout_completed = workout_completed

    # ---------------- Save newly completed sets ----------------
    last_saved_sets = int(
        st.session_state.get("last_saved_sets_completed", 0) or 0
    )

    newly_completed = max(0, sets_completed - last_saved_sets)

    if newly_completed > 0:
        now = time.time()

        started_at = st.session_state.get(
            "set_cycle_started_at", now
        )

        time_taken = max(0, now - started_at)
        user_id = st.session_state.get("user_id", 0)

        try:
            add_exercise(
                user_id,
                exercise,
                newly_completed * reps_per_set,
                newly_completed,
                time_taken,
            )

            # Update after successful persistence to avoid duplicate saves.
            st.session_state.last_saved_sets_completed = sets_completed
            st.session_state.set_cycle_started_at = now

        except Exception as exc:
            print(
                "[Metrics] Could not save completed set:",
                repr(exc),
            )
            st.session_state.coach_feedback = (
                f"Could not save workout history: {exc}"
            )

    # ---------------- Workout completion ----------------
    already_notified = st.session_state.get(
        "last_notified_workout_complete", False
    )

    if workout_completed and not already_notified:
        # Set this before calling the pipeline to prevent duplicate events.
        st.session_state.last_notified_workout_complete = True

        _send_coach_event(
            event="workout_completed",
            exercise=exercise,
            metrics=latest_metrics,
        )

        # Do not let a form-check message overwrite the final message.
        return

    # ---------------- Set completion ----------------
    if newly_completed > 0:
        _send_coach_event(
            event="set_completed",
            exercise=exercise,
            metrics=latest_metrics,
        )

    # ---------------- Pose detection ----------------
    pose_detected = latest_metrics.get("pose_detected", True)

    if not pose_detected:
        now = time.time()

        last_warning = st.session_state.get(
            "last_no_pose_feedback_at", 0
        )

        if now - last_warning >= 10:
            st.session_state.last_no_pose_feedback_at = now

            _send_coach_event(
                event="no_pose_detected",
                exercise=exercise,
                metrics={
                    "issue": (
                        "No pose detected. Please step into "
                        "the camera frame."
                    )
                },
            )

        return

    # Reset the no-pose timer once the user returns to the frame.
    st.session_state.last_no_pose_feedback_at = 0

    # ---------------- Ongoing form correction ----------------
    _send_coach_event(
        event="ongoing_form_check",
        exercise=exercise,
        metrics=latest_metrics,
    )