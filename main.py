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
# [NEW: coaching] Guided workout plans, state machine runner, adaptive difficulty & Claude coach
from services.workout_plans import (
    get_all_plans,
    get_plan_by_id,
    get_supported_goals,
)
from core.session_tracker import WorkoutRunner, WorkoutState
from services.adaptive import (
    evaluate_set_performance,
    load_exercise_progression,
    save_exercise_progression,
)
from services.coach_llm import generate_workout_summary


load_dotenv()



def initialize_voice_pipeline():
    """Initialize the Groq-powered coaching pipeline."""

    if st.session_state.get("voice_pipeline") is not None:
        return

    try:
        api_key = os.environ.get("GROQ_API_KEY", "").strip().strip('"').strip("'")

        if not api_key:
            try:
                api_key = st.secrets.get("GROQ_API_KEY", "").strip().strip('"').strip("'")
            except Exception:
                api_key = ""

        if not api_key:
            env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
            if os.path.exists(env_file):
                try:
                    with open(env_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip().startswith("GROQ_API_KEY="):
                                api_key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                                break
                except Exception:
                    pass

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


# [NEW: coaching] Helper to speak guided runner voice cues via the voice pipeline
def play_guided_cue(cue_text: str):
    """Deliver a guided runner voice announcement via the existing TTS pipeline."""
    pipeline = st.session_state.get("voice_pipeline")
    if pipeline:
        res = pipeline.speak_direct(cue_text, is_form_cue=False)
        if res:
            audio, text = res
            st.session_state.audio_to_play = audio
            st.session_state.coach_feedback = text



# [NEW: coaching] Post-Workout Summary Screen
def render_post_workout_summary(runner: WorkoutRunner):
    """Render structured post-workout screen powered by Claude API with local fallback."""
    st.markdown("## 🏁 Workout Complete!")
    st.markdown("### Outstanding job! Here is your AI Coach performance breakdown.")

    stats = runner.tracker.get_compact_stats()

    # Cached Claude summary to prevent redundant API calls on reruns
    if "cached_summary" not in st.session_state:
        with st.spinner("Generating personalized AI coaching summary..."):
            st.session_state.cached_summary = generate_workout_summary(stats)

    summary_data = st.session_state.cached_summary

    # Key metrics row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Reps", f"{stats.get('total_reps_completed', 0)} / {stats.get('total_reps_target', 0)}")
    with col2:
        st.metric("Completion", f"{stats.get('completion_rate_pct', 0):.0f}%")
    with col3:
        mins = int(stats.get("duration_sec", 0) // 60)
        secs = int(stats.get("duration_sec", 0) % 60)
        st.metric("Duration", f"{mins}m {secs}s")
    with col4:
        st.metric("Form Score", f"{stats.get('avg_form_score', 0):.0f}%")

    st.markdown("---")

    summary_text = summary_data.get("summary", "")
    if summary_text:
        st.info(f"📋 **Coach Assessment:** {summary_text}")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("#### 🏆 Key Wins")
        for win in summary_data.get("wins", []):
            st.markdown(f"<div class='badge-win'>✅ {win}</div>", unsafe_allow_html=True)

        st.markdown("#### ⚠️ Focus Areas")
        for imp in summary_data.get("improvements", []):
            st.markdown(f"<div class='badge-improv'>🔍 {imp}</div>", unsafe_allow_html=True)

    with col_right:
        st.markdown("#### 💡 Actionable Tips")
        for tip in summary_data.get("tips", []):
            st.markdown(f"<div class='badge-tip'>💡 {tip}</div>", unsafe_allow_html=True)

        st.markdown("#### 📈 Next Session Progression")
        for nxt in summary_data.get("next_session", []):
            st.markdown(f"<div class='badge-next'>🚀 {nxt}</div>", unsafe_allow_html=True)

    # Persist progression adjustments locally to data/progression.json
    for ex in stats.get("exercises", []):
        ex_name = ex.get("exercise")
        if ex_name:
            rec = summary_data.get("next_session", [""])[0] if summary_data.get("next_session") else "Maintain current target"
            save_exercise_progression(
                exercise_name=ex_name,
                suggested_target_reps=ex.get("reps_completed", 10),
                reason=rec,
            )



    if st.button("Start New Workout", use_container_width=True, key="start_new_workout_btn"):
        st.session_state.workout_runner = None
        st.session_state.workout_started = False
        st.session_state.pop("cached_summary", None)
        st.rerun()


# [NEW: coaching] Guided Workout HUD
def render_guided_hud(runner: WorkoutRunner):
    """Render the active guided routine HUD: state, exercise, rest timer, progress bar."""
    ui = runner.get_ui_state()

    # Progress bar across entire routine
    st.markdown(
        f"""
        <div class="routine-progress-container">
            <div class="routine-progress-bar" style="width: {int(ui['overall_progress'] * 100)}%;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #94a3b8; margin-bottom: 12px;">
            <span>Overall Routine Progress</span>
            <span>Set {ui['completed_sets']} of {ui['total_sets']} ({int(ui['overall_progress'] * 100)}%)</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if ui["state"] == WorkoutState.REST.value:
        st.markdown(
            f"""
            <div class="rest-banner">
                <div class="rest-label">⏱️ Rest Interval</div>
                <div class="rest-time-digits">{ui['rest_remaining']:02d}s</div>
                <div class="up-next-box">
                    <span class="up-next-title">Up Next:</span>
                    <span class="up-next-val">{ui['up_next']}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_skip, col_pause = st.columns(2)
        with col_skip:
            if st.button("⏭️ Skip Rest", key="guided_skip_rest_btn", use_container_width=True):
                runner.skip()
                st.rerun()
        with col_pause:
            pause_label = "▶️ Resume" if ui["is_paused"] else "⏸️ Pause"
            if st.button(pause_label, key="guided_pause_rest_btn", use_container_width=True):
                if ui["is_paused"]:
                    runner.resume()
                else:
                    runner.pause()
                st.rerun()

    else:
        # Active Exercise Set
        st.markdown(
            f"""
            <div class="guided-hud-box">
                <div class="guided-set-indicator">Set {ui['current_set']} of {ui['target_sets']}</div>
                <div class="guided-exercise-title">{ui['exercise_name']}</div>
                <div class="guided-form-cue">🎯 <strong>Form Cue:</strong> {ui['form_cue']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Target Reps", ui["target_reps"])
        with col2:
            st.metric("Current Reps", f"{ui['current_reps']} / {ui['target_reps']}")

        # Adaptive difficulty check mid-set
        if runner.current_exercise and runner.tracker._current_set_reps:
            dec = evaluate_set_performance(
                rep_records=runner.tracker._current_set_reps,
                target_reps=ui["target_reps"],
                exercise_name=ui["exercise_name"],
            )
            if dec.action == "suggest_stop":
                st.warning(f"⚠️ **Coach Suggestion:** {dec.reason}")
                if dec.voice_cue and not st.session_state.get("last_adaptive_cue"):
                    play_guided_cue(dec.voice_cue)
                    st.session_state["last_adaptive_cue"] = True
            elif dec.action == "suggest_lower":
                st.info(f"💡 **Coach Suggestion:** {dec.reason}")
                if dec.voice_cue and not st.session_state.get("last_adaptive_cue"):
                    play_guided_cue(dec.voice_cue)
                    st.session_state["last_adaptive_cue"] = True

        # Controls row
        col_pause, col_skip, col_end = st.columns(3)
        with col_pause:
            pause_label = "▶️ Resume" if ui["is_paused"] else "⏸️ Pause"
            if st.button(pause_label, key="guided_pause_btn", use_container_width=True):
                if ui["is_paused"]:
                    runner.resume()
                else:
                    runner.pause()
                st.rerun()
        with col_skip:
            if st.button("⏭️ Skip Set", key="guided_skip_btn", use_container_width=True):
                runner.skip()
                st.rerun()
        with col_end:
            if st.button("⏹️ End Workout", key="guided_end_btn", use_container_width=True):
                runner.end_workout()
                st.rerun()


def main():
    st.set_page_config(
        page_icon="🏋️‍♀️",
        page_title="AI Real-time GYM Coach",
        initial_sidebar_state="expanded",
        layout="centered",
    )

    load_css(os.path.join(os.getcwd(), "static", "style.css"))

    # [NEW: coaching] Load guided coach styling if available
    coach_css = os.path.join(os.getcwd(), "static", "css", "coach.css")
    if os.path.exists(coach_css):
        load_css(coach_css)

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
        st.markdown(
            """
            <div class="sidebar-brand-box">
                <div class="brand-chip">🏋️ AIBUDDY</div>
                <div class="brand-tagline">Real-Time AI Gym Coach</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        username = st.session_state.get("username")
        if username:
            col_user, col_logout = st.columns([3, 1])
            with col_user:
                st.caption(f"👤 Logged in as **{username}**")
            with col_logout:
                if st.button("Logout", key="logout_btn", help="Sign out"):
                    st.session_state.clear()
                    st.rerun()

        st.divider()

        # [NEW: coaching] Workout Mode Selector (Opt-in)
        workout_mode_label = st.radio(
            "Workout Mode",
            options=["Free Workout", "Guided Routine"],
            index=0 if st.session_state.get("workout_mode", "free") == "free" else 1,
            key="mode_radio_select",
            disabled=st.session_state.get("workout_started", False),
        )
        st.session_state.workout_mode = "guided" if workout_mode_label == "Guided Routine" else "free"

        st.divider()

        # =====================================================================
        # GUIDED ROUTINE SIDEBAR
        # =====================================================================
        if st.session_state.workout_mode == "guided":
            st.subheader("Guided Workout Plan")

            if not workout_started:
                goals = get_supported_goals()
                selected_goal = st.selectbox("Fitness Goal", options=goals, key="guided_goal_select")
                all_plans = get_all_plans()
                active_plan_id = "fat_loss"
                for p_id, p_data in all_plans.items():
                    if p_data["goal"] == selected_goal:
                        active_plan_id = p_id
                        break
                selected_plan = all_plans[active_plan_id]

                st.caption(f"ℹ️ {selected_plan['description']}")
                st.caption(f"⏱️ Est. Duration: ~{selected_plan['estimated_duration_min']} mins")

                with st.expander("📋 Exercises in Routine", expanded=True):
                    for ex in selected_plan["exercises"]:
                        note = f" *({ex['substitution_note']})*" if ex.get("substitution_note") else ""
                        st.markdown(f"- **{ex['exercise_name']}**: {ex['sets']} sets × {ex['reps']} reps{note}")

                if st.button("Start Guided Routine", use_container_width=True, key="start_guided_session_btn"):
                    runner = WorkoutRunner(selected_plan)
                    runner.start_workout()
                    st.session_state.workout_runner = runner
                    st.session_state.exercise_type = runner.current_exercise["exercise_name"]
                    st.session_state.workout_started = True
                    st.session_state.pop("cached_summary", None)

                    # Trigger initial start cues
                    for cue in runner.pop_voice_cues():
                        play_guided_cue(cue)

                    st.rerun()

            else:
                runner = st.session_state.get("workout_runner")
                if runner and runner.current_exercise:
                    ex_name = runner.current_exercise["exercise_name"]
                    st.info(f"**Current:** {ex_name} — Set {runner.current_set_idx}/{runner.current_exercise.get('sets', 1)}")

                if st.button("End Workout", key="end_guided_session_btn", use_container_width=True):
                    if runner:
                        runner.end_workout()
                    st.session_state.workout_started = False
                    st.rerun()

        # =====================================================================
        # FREE WORKOUT SIDEBAR (100% UNTOUCHED ORIGINAL FLOW)
        # =====================================================================
        else:
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

            # Workout progress (Free Mode)
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
    st.markdown(
        """
        <div class="app-hero-header">
            <div class="hero-status-pill"><span class="pulse-dot"></span> LIVE POSE TRACKING & AI COACHING</div>
            <h1 class="hero-main-title">AIBuddy <span class="gradient-text">Gym Coach</span></h1>
            <p class="hero-subtext">Precision computer vision rep counting, live form biomechanics, and personalized voice guidance</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    feedback = st.session_state.get("coach_feedback")

    if feedback:
        st.markdown(
            f"""
            <div class="coach-voice-banner">
                <span class="coach-avatar">🤖</span>
                <div class="coach-speech-content">
                    <span class="coach-label">AI Coach Voice Feedback</span>
                    <p class="coach-message">{feedback}</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Autoplay the latest coach audio (plays once per new message)
    render_coach_audio()

    # =========================================================================
    # MAIN CONTENT: POST-WORKOUT SUMMARY SCREEN (If Guided Routine Complete)
    # =========================================================================
    runner: Optional[WorkoutRunner] = st.session_state.get("workout_runner")
    if (
        st.session_state.get("workout_mode") == "guided"
        and runner is not None
        and runner.state == WorkoutState.COMPLETE
    ):
        render_post_workout_summary(runner)
        return

    # =========================================================================
    # MAIN CONTENT: GUIDED ROUTINE HUD (When Active)
    # =========================================================================
    if (
        st.session_state.get("workout_mode") == "guided"
        and st.session_state.get("workout_started", False)
        and runner is not None
    ):
        render_guided_hud(runner)

        # Synchronize current active exercise from runner to session state
        if runner.current_exercise:
            active_ex = runner.current_exercise["exercise_name"]
            if st.session_state.get("exercise_type") != active_ex:
                st.session_state.exercise_type = active_ex

        # Pop any runner voice cues (e.g. rest countdown, next up)
        for cue in runner.pop_voice_cues():
            play_guided_cue(cue)

    # ---------------- Camera ----------------
    if not st.session_state.get("workout_started", False):
        if st.session_state.get("workout_mode") == "guided":
            st.markdown(
                """
                <div style="
                    border: 1px dashed rgba(56, 189, 248, 0.35);
                    border-radius: 14px;
                    padding: 38px 24px;
                    text-align: center;
                    background: rgba(56, 189, 248, 0.04);
                    margin: 24px 0;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
                ">
                    <div style="font-size: 2.2rem; margin-bottom: 8px;">🎯</div>
                    <h3 style="color: #38BDF8; margin-bottom: 6px; font-weight: 700;">Select a Guided Program</h3>
                    <p style="color: #94A3B8; font-size: 0.92rem; margin: 0 auto; max-width: 500px; line-height: 1.5;">
                        Choose your fitness goal in the sidebar (<strong>Fat Loss</strong>, <strong>Strength</strong>, or <strong>Beginner</strong>) and click <strong>Start Guided Routine</strong> to begin your coached session.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div style="
                    border: 1px dashed rgba(255, 255, 255, 0.16);
                    border-radius: 14px;
                    padding: 38px 24px;
                    text-align: center;
                    background: rgba(18, 24, 38, 0.5);
                    margin: 24px 0;
                    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
                ">
                    <div style="font-size: 2.2rem; margin-bottom: 8px;">👈</div>
                    <h3 style="color: #F8FAFC; margin-bottom: 6px; font-weight: 700;">Set Your Workout Plan</h3>
                    <p style="color: #94A3B8; font-size: 0.92rem; margin: 0 auto; max-width: 480px; line-height: 1.5;">
                        Choose your exercise, sets and reps in the sidebar, then click <strong>Start Workout</strong> to activate the camera and AI coach.
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

        inject_webrtc_styles()

    render_workout_history()



    # Auto-rerun loop: triggers during video streaming OR active guided rest intervals
    is_active_guided_rest = (
        st.session_state.get("workout_mode") == "guided"
        and runner is not None
        and runner.state == WorkoutState.REST
        and not runner.is_paused
    )

    if (
        st.session_state.get("workout_started", False)
        and (
            (context is not None and context.state.playing)
            or is_active_guided_rest
        )
    ):
        if is_active_guided_rest and runner is not None:
            runner.tick_rest(0.5)
            for cue in runner.pop_voice_cues():
                play_guided_cue(cue)

        time.sleep(0.5)
        st.rerun()


if __name__ == "__main__":
    main()
