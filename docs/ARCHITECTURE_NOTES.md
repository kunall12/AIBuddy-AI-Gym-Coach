# AIBuddy AI Gym Coach — Existing Architecture & Behavior Map

This document outlines the existing architecture, data flow, supported exercises, and internal event system of **AIBuddy AI Gym Coach** prior to the introduction of guided coaching, LLM summaries, and adaptive difficulty.

---

## 1. High-Level Technology Stack & Lifecycle

- **Web Framework**: [Streamlit](https://streamlit.io) (v1.54.0), running on top of an internal **Tornado** web server.
- **Frontend / Client-Server Communication**:
  - **WebSocket**: Bidirectional Streamlit protocol connecting browser to backend for UI reruns, widget states, and DOM updates.
  - **WebRTC**: Real-time peer-to-peer audio/video streaming via `streamlit-webrtc` (v0.64.5) with STUN server (`stun:stun.l.google.com:19302`).
- **Computer Vision & Pose Estimation**: [MediaPipe](https://developers.google.com/mediapipe) (v0.10.14) with `ml_models/pose_landmarker_full.task` in `RunningMode.VIDEO` at 30 fps increments.
- **Voice Synthesis & AI Coaching**:
  - TTS: `gTTS` (Google Text-to-Speech v2.5.3) generating in-memory MP3 audio streams.
  - LLM Coaching: Groq API (`openai/gpt-oss-120b`) producing short, motivating real-time cues.
- **Persistence**: SQLite database (`data.db`) storing `users` and `exercises` history.

---

## 2. Key Files & Directory Responsibilities

| Path | Primary Responsibility |
|------|------------------------|
| `main.py` | App entrypoint: page layout, login wall check, voice pipeline initialization, sidebar workout parameters (exercise, sets, reps), WebRTC streamer element, metrics sync, hidden audio player, workout history table, and auto-rerun loop (`st.rerun()` every ~0.5s when active). |
| `core/base_exercise.py` | Abstract base class `BaseExercise` with `reps`, `stage`, 3-point angle math (`calculate_angle`), and landmark extraction (`get_point`). |
| `detectors/squat.py` | `SquatDetector`: calculates knee and back angles; tracks "down" (<100°) and "up" (>=160°) stages; checks depth status ("GOOD DEPTH", "TOO HIGH", "STANDING"). |
| `detectors/pushup.py` | `PushUpDetector`: calculates elbow and body alignment angles; tracks hip sag/piking relative to shoulder-ankle midpoint; increments rep on elbow extension (>160°). |
| `detectors/biceps_curl.py` | `BicepsCurlDetector`: calculates elbow angle; detects elbow drift from shoulder and torso swinging from vertical; increments rep when returning to down position (>160°). |
| `detectors/shoulder_press.py` | `ShoulderPressDetector`: calculates elbow extension (>160°) and press down (<90°); tracks back arch status ("Neutral", "Slight Arch", "Excessive Arch"). |
| `detectors/lunges.py` | `LungesDetector`: tracks front knee angle (down <100°, up >160°) and torso angle; detects lateral torso/hip balance offset. |
| `services/vision/exercise_video_processor.py` | `VideoProcessorClass(VideoProcessorBase)`: WebRTC frame receiver (`recv`), flips image, runs MediaPipe pose landmarker, draws green skeleton and blue keypoints, calls active exercise detector, draws diagnostic HUD overlays, and thread-safely stores latest metrics. |
| `services/tracking/metrics.py` | `sync_metrics_update(context)`: runs on each Streamlit render cycle, extracts latest metrics from video processor, updates `st.session_state`, checks set completion, logs newly completed sets to SQLite, and fires coaching events. |
| `services/coaching/voice_pipeline.py` | Orchestrates form error extraction (`_find_form_issue`), calls `LLMCoach.give_feedback`, invokes `TextToSpeech.speak`, and enforces cooldowns between spoken feedback. |
| `services/coaching/llm.py` | Calls Groq API with system prompt (`PROMPT` from `workout_config.py`) and rolling 10-message conversational history to produce 10–15 word voice cues. |
| `services/coaching/tts.py` | `TextToSpeech.speak(text)`: converts text into in-memory MP3 bytes using `gTTS`. |
| `services/config/workout_config.py` | Constants: supported exercise list (`EXERCISE_OPTIONS`), skeleton connection pairs (`POSE_CONNECTIONS`), exercise-specific session metrics fields, and the LLM system prompt. |
| `services/persistence/exercise_repository.py` | SQLite schema setup (`init_db`) and operations: `get_or_create_user`, `add_exercise` (aggregates daily reps/sets/time per exercise), `get_users_exercises`. |
| `services/auth/login_wall.py` | Username login form preventing unauthenticated users from starting sessions. |
| `services/state/session_defaults.py` | Sets initial session keys and defaults in `st.session_state`. |
| `services/ui/style_loader.py` | Injects custom CSS (`static/style.css`), local OTF font (`AdobeClean.otf`), and WebRTC frame styles. |

---

## 3. Data Flow: From Camera Frame to Rep Count to Feedback

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Browser WebRTC Camera Stream                             │
└──────────────────────────────┬──────────────────────────────┘
                               │ H.264 / VP8 Video Frames
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. VideoProcessorClass.recv(frame) (Background Thread)      │
│    - cv2.flip(frame, 1)                                     │
│    - MediaPipe PoseLandmarker.detect_for_video()            │
│    - If pose detected:                                      │
│        * _draw_skeleton(img, landmarks)                     │
│        * detector = _detectors[exercise_type]               │
│        * metrics = detector.process(landmarks)             │
│        * _draw_overlays(img, metrics, ex_type)              │
│        * set_latest_metrics(metrics) [Locked]               │
│    - If no pose:                                            │
│        * _draw_no_pose_warnings(img)                        │
│        * set_latest_metrics({"pose_detected": False})       │
└──────────────────────────────┬──────────────────────────────┘
                               │ Latest Metrics Snapshot
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. sync_metrics_update(context) (Streamlit Main Loop ~0.5s) │
│    - processor.get_latest_metrics()                         │
│    - Update st.session_state (reps, angles, statuses)       │
│    - Check Set Progress:                                    │
│        sets_completed = min(reps // reps_per_set, target)   │
│        current_set_reps = reps % reps_per_set               │
│        workout_completed = reps >= reps_per_set * target    │
│    - If new set completed:                                  │
│        * add_exercise(user_id, exercise, reps, sets, time)  │
│        * _send_coach_event("set_completed", ...)            │
│    - If workout completed and not yet notified:             │
│        * _send_coach_event("workout_completed", ...)        │
│    - If no pose detected for >= 10s:                        │
│        * _send_coach_event("no_pose_detected", ...)         │
│    - Otherwise:                                             │
│        * _send_coach_event("ongoing_form_check", ...)       │
└──────────────────────────────┬──────────────────────────────┘
                               │ (event, exercise, metrics)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. VoicePipeline.process_event(...)                         │
│    - _find_form_issue(exercise, metrics)                    │
│    - Check cooldown (minimum 5s between ongoing cues)       │
│    - llm.give_feedback(event, issue) -> Text Cue            │
│    - tts.speak(text) -> MP3 Bytes                           │
│    - Store in st.session_state:                             │
│        * audio_to_play = mp3_bytes                          │
│        * coach_feedback = text_cue                          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Browser Audio Playback (render_coach_audio)              │
│    - Streamlit renders hidden <audio> tag with autoplay     │
│    - Text cue rendered in st.success banner                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Existing Events & Coaching Triggers

The voice pipeline handles the following discrete events:

1. `workout_started`: Triggered immediately when the user clicks "Start Workout" in the sidebar. Major event (no throttle).
2. `ongoing_form_check`: Evaluated every ~0.5s during exercise. Filtered by `_find_form_issue()`; only speaks if an error is active AND at least 5 seconds have elapsed since the last voice cue.
3. `set_completed`: Triggered when `reps` reaches a multiple of `reps_per_set`. Logs to database. Major event (no throttle).
4. `workout_completed`: Triggered when `sets_completed == target_sets`. Major event (no throttle).
5. `no_pose_detected`: Triggered when `pose_detected == False` persists for 10 or more seconds.

---

## 5. Supported Exercises & Form Validation Rules

| Exercise Name | Angle Metrics | Form Error Conditions Tracked |
|---------------|---------------|-------------------------------|
| **Squats** | Knee Angle (down <100°, up >=160°), Back Angle | `depth_status == "TOO HIGH"` (insufficient knee bend); `back_angle < 130°` (excessive forward lean). |
| **Push-ups** | Elbow Angle (down <90°, up >160°), Body Angle | `body_alignment == "Poor Form"` (`body_angle <= 140°`); `hip_status == "SAGGING"` (`hip_deviation > 0.08`); `hip_status == "PIKED UP"` (`hip_deviation < -0.08`). |
| **Biceps Curls (Dumbbell)** | Elbow Angle (up <50°, down >160°) | `shoulder_status == "ELBOW DRIFTING"` (`elbow_drift > 0.06`); `swing_status == "SWINGING"` (`torso_angle > 15°`). |
| **Shoulder Press** | Elbow Angle (up >160°, down <90°) | `back_arch_status == "Excessive Arch"` (`back_angle < 140°`); `back_arch_status == "Slight Arch"` (`back_angle < 160°`). |
| **Lunges** | Front Knee Angle (down <100°, up >160°), Torso Angle | `balance_status == "OFF BALANCE"` (`lateral_offset > 0.10`). |
