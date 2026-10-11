import os
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from streamlit_webrtc import webrtc_streamer, WebRtcMode

from services.auth.login_wall import render_login_wall
from services.state.session_defaults import initial_session_defaults
from services.config.workout_config import EXERCISE_OPTIONS
from services.ui.style_loader import (
    load_css,
    inject_local_font,
    inject_webrtc_styles,
)
from services.persistence.exercise_repository import (
    init_db,
    get_users_exercises,
)
from services.vision.exercise_video_processor import VideoProcessorClass
from services.tracking.metrics import sync_metrics_update
from services.coaching.llm import LLMCoach
from services.coaching.tts import TextToSpeech
from services.coaching.voice_pipeline import VoicePipeline


load_dotenv()


def initialize_voice_pipeline():
    """Initialize the Groq-powered coaching pipeline."""

    if st.session_state.get("voice_pipeline") is not None:
        return

    try:
        api_key = os.environ.get("GROQ_API_KEY", "").strip()

        if not api_key:
            try:
                api_key = st.secrets.get("GROQ_API_KEY", "").strip()
            except Exception:
                api_key = ""

        if not api_key:
            raise ValueError(
                "GROQ_API_KEY was not found in .env or Streamlit secrets."
            )

        client = Groq(api_key=api_key)
        llm = LLMCoach(client)
        tts = TextToSpeech()

        st.session_state.voice_pipeline = VoicePipeline(llm, tts)
        st.session_state.voice_pipeline_error = None

    except Exception as exc:
        st.session_state.voice_pipeline = None
        st.session_state.voice_pipeline_error = (
            f"{type(exc).__name__}: {exc}"
        )
        print("VOICE PIPELINE INITIALIZATION ERROR:", repr(exc))


def generate_coach_feedback(event, exercise, metrics=None):
    """Generate coaching feedback and retain it for display."""

    pipeline = st.session_state.get("voice_pipeline")

    if pipeline is None:
        error = st.session_state.get(
            "voice_pipeline_error",
            "Voice pipeline is not initialized.",
        )
        st.session_state.coach_feedback = f"Coach unavailable: {error}"
        return

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

    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        st.session_state.coach_feedback = f"Coach error: {message}"
        print(f"[Coach] {event} failed: {message}")


def render_coach_audio():
    """Play the newest coach message automatically, with no player shown.

    st.audio(autoplay=True) is Streamlit's own autoplay. Every new message is
    new audio bytes, so Streamlit gives it a new URL and the browser plays it.
    The same bytes on later reruns keep the same URL, so nothing replays.
    """

    audio = st.session_state.get("audio_to_play")

    if not audio:
        return

    # Hide the player bar; a hidden audio element still plays.
    st.markdown(
        "<style>[data-testid='stAudio'] {display: none;}</style>",
        unsafe_allow_html=True,
    )
    st.audio(audio, format="audio/mp3", autoplay=True)


def render_workout_metrics(exercise):
    """Display the metrics associated with the selected exercise."""

    definitions = {
        "Squats": [
            ("Knee Angle", "knee_angle", True),
            ("Back Angle", "back_angle", True),
            ("Depth Status", "depth_status", False),
        ],
        "Push-ups": [
            ("Elbow Angle", "elbow_angle", True),
            ("Body Alignment", "body_alignment", False),
            ("Hip Position", "hip_status", False),
        ],
        "Biceps Curls (Dumbbell)": [
            ("Elbow Angle", "elbow_angle", True),
            ("Shoulder Stability", "shoulder_status", False),
            ("Swing Detection", "swing_status", False),
        ],
        "Shoulder Press": [
            ("Elbow Angle", "elbow_angle", True),
            ("Arm Extension", "extension_status", False),
            ("Back Arch", "back_arch_status", False),
        ],
        "Lunges": [
            ("Front Knee Angle", "front_knee_angle", True),
            ("Torso Angle", "torso_angle", True),
            ("Balance Status", "balance_status", False),
        ],
    }

    for label, key, is_angle in definitions.get(exercise, []):
        value = st.session_state.get(key)

        if value is None:
            display_value = "N/A"
        elif is_angle:
            try:
                display_value = f"{float(value):.1f}°"
            except (TypeError, ValueError):
                display_value = "N/A"
        else:
            display_value = str(value)

        st.metric(label, display_value)


def render_workout_history():
    """Display the current user's workout history."""

    st.divider()
    st.markdown("#### Workout History")

    user_id = st.session_state.get("user_id")

    if user_id is None:
        st.info("User ID is not available.")
        return

    try:
        history_rows = get_users_exercises(user_id)

        records = [
            {
                "Exercise": row["exercise_name"],
                "Reps": row["reps"],
                "Sets": row["sets"],
                "Time (sec)": row["time"],
                "Date": row["created_at"],
            }
            for row in history_rows
        ]

        df = pd.DataFrame(records)

        if df.empty:
            st.info("No workout history found.")
            return

        df["Date"] = pd.to_datetime(df["Date"]).dt.date

        grouped = (
            df.groupby(["Exercise", "Date"])
            .agg(
                {
                    "Reps": "sum",
                    "Sets": "sum",
                    "Time (sec)": "sum",
                }
            )
            .reset_index()
        )

        grouped.index += 1
        st.table(grouped, border="horizontal")

    except Exception as exc:
        st.error(
            f"Could not load workout history: "
            f"{type(exc).__name__}: {exc}"
        )


def main():
    st.set_page_config(
        page_icon="🏋️‍♀️",
        page_title="AI Real-time GYM Coach",
        initial_sidebar_state="expanded",
        layout="centered",
    )

    load_css(os.path.join(os.getcwd(), "static", "style.css"))

    inject_local_font(
        os.path.join(os.getcwd(), "static", "AdobeClean.otf"),
        "AdobeClean",
    )

    init_db()

    if not render_login_wall():
        return

    initial_session_defaults()
    initialize_voice_pipeline()

    if st.session_state.get("voice_pipeline") is None:
        st.warning("AI voice coach is unavailable.")
        error = st.session_state.get("voice_pipeline_error")

        if error:
            st.error(error)

    workout_started = st.session_state.get(
        "workout_started", False
    )

    context = None

    # ---------------- Sidebar ----------------
    with st.sidebar:
        st.title("🏋️‍♂️ Apna AI Coach")

        username = st.session_state.get("username")
        if username:
            st.caption(f"👤 Logged in as {username}")

        st.divider()
        st.subheader("Workout Plan")

        if not workout_started:
            plan_exercise = st.selectbox(
                "Exercise",
                options=EXERCISE_OPTIONS,
                key="plan_exercise",
            )

            plan_sets = st.number_input(
                "Sets",
                min_value=0,
                max_value=50,
                step=1,
                key="plan_sets",
            )

            plan_reps = st.number_input(
                "Reps per Set",
                min_value=0,
                max_value=50,
                step=1,
                key="plan_reps",
            )

            if st.button(
                "Start Workout",
                use_container_width=True,
                key="start_session_button",
            ):
                if plan_sets <= 0 or plan_reps <= 0:
                    st.warning("Choose at least 1 set and 1 rep.")
                else:
                    st.session_state.exercise_type = plan_exercise
                    st.session_state.target_sets = int(plan_sets)
                    st.session_state.reps_per_set = int(plan_reps)
                    st.session_state.reps = 0
                    st.session_state.current_set_reps = 0
                    st.session_state.sets_completed = 0
                    st.session_state.workout_completed = False
                    st.session_state.workout_started = True

                    st.session_state.set_cycle_started_at = time.time()
                    st.session_state.last_saved_sets_completed = 0
                    st.session_state.last_notified_sets_completed = 0
                    st.session_state.last_notified_workout_complete = False
                    st.session_state.last_no_pose_feedback_at = 0

                    generate_coach_feedback(
                        "workout_started",
                        plan_exercise,
                        {},
                    )

                    st.rerun()

        else:
            exercise = st.session_state.get(
                "exercise_type", "Squats"
            )

            st.info(
                f"**{exercise}** — "
                f"{st.session_state.get('target_sets', 0)} Sets / "
                f"{st.session_state.get('reps_per_set', 0)} Reps"
            )

            if st.button(
                "End Workout",
                key="end_session_button",
                use_container_width=True,
            ):
                generate_coach_feedback(
                    "workout_completed",
                    exercise,
                    {},
                )

                st.session_state.workout_started = False
                st.rerun()

        # Workout progress
        if st.session_state.get("workout_started", False):
            exercise = st.session_state.get(
                "exercise_type", "Squats"
            )

            st.divider()
            st.subheader("Progress")

            st.metric(
                "Total Reps",
                st.session_state.get("reps", 0),
            )
            st.metric(
                "Current Set Reps",
                f"{st.session_state.get('current_set_reps', 0)} / "
                f"{st.session_state.get('reps_per_set', 0)}",
            )
            st.metric(
                "Sets Completed",
                f"{st.session_state.get('sets_completed', 0)} / "
                f"{st.session_state.get('target_sets', 0)}",
            )

            st.divider()
            st.subheader(f"{exercise} Metrics")
            render_workout_metrics(exercise)

    # ---------------- Main page ----------------
    st.title("AI Real-time GYM Coach")
    st.markdown(
        "#### Real-time pose detection with proactive AI voice coaching"
    )

    feedback = st.session_state.get("coach_feedback")

    if feedback:
        st.success(f"🤖 **Coach:** {feedback}")

    # Autoplay the latest coach audio (plays once per new message)
    render_coach_audio()

    # ---------------- Camera ----------------
    if not st.session_state.get("workout_started", False):
        st.markdown(
            """
            <div style="
                border: 2px dashed #444;
                border-radius: 12px;
                padding: 36px 24px;
                text-align: center;
                color: #888;
                margin: 28px 0;
            ">
                <h2 style="color:#ccc;">👈 Set your workout plan</h2>
                <p>
                    Choose your exercise, sets and reps in the sidebar,
                    then click <strong>Start Workout</strong> to activate
                    the camera and AI coach.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:
        context = webrtc_streamer(
            key="exercise-analysis",
            mode=WebRtcMode.SENDRECV,
            video_processor_factory=VideoProcessorClass,
            rtc_configuration={
                "iceServers": [
                    {"urls": ["stun:stun.l.google.com:19302"]}
                ]
            },
            media_stream_constraints={
                "video": True,
                "audio": False,
            },
            async_processing=True,
        )

        try:
            sync_metrics_update(context)
        except Exception as exc:
            st.error(
                f"Metrics update failed: {type(exc).__name__}: {exc}"
            )
            print("METRICS UPDATE ERROR:", repr(exc))

        # NOTE: live form coaching is already triggered inside
        # sync_metrics_update() (services/tracking/metrics.py), which sets
        # st.session_state.audio_to_play. render_coach_audio() plays it.

        inject_webrtc_styles()

    render_workout_history()

    # IMPORTANT: refresh only after the current page has been rendered.
    # This allows updated metrics and newly generated feedback to appear.
    if (
        st.session_state.get("workout_started", False)
        and context is not None
        and context.state.playing
    ):
        time.sleep(0.5)
        st.rerun()


if __name__ == "__main__":
    main()