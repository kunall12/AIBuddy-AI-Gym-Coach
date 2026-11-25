# 🏋️‍♂️ AIBuddy — Real-Time AI Gym Coach

A real-time AI gym coach with live pose detection, automated rep counting, biomechanical form feedback, voice synthesis, guided routines, adaptive difficulty, and Claude-powered coach chat.

---

## 🚀 Key Features

### 1. Real-Time Pose Tracking & Rep Counting (Free Workout)
- **Computer Vision**: Powered by MediaPipe Pose Landmarker (`RunningMode.VIDEO`) streaming at 30 fps via WebRTC.
- **Form Error Analysis & HUD**: Real-time diagnostic overlays for joint angles and posture.
- **5 Supported Exercises**:
  - **Squats**: Tracks knee angle depth (<100° down, ≥160° up) and torso/back angle.
  - **Push-ups**: Tracks elbow angle (<90° down, >160° up), straight body alignment, and hip sagging/piking.
  - **Biceps Curls (Dumbbell)**: Tracks elbow flexion (<50° up, >160° down), elbow drift from torso, and torso swinging.
  - **Shoulder Press**: Tracks overhead extension (>160° up, <90° down) and lumbar arching.
  - **Lunges**: Tracks front knee flexion (<100° down, >160° up), torso angle, and lateral balance offset.

### 2. Guided Workout Plans & Runner State Machine (Feature 1)
- **Data-Driven Goal Picker**: Choose from **Fat Loss**, **Strength**, and **Beginner** routines. Adding new plans is purely adding data in `services/workout_plans.py`.
- **State Machine Runner**: Manages transitions between `PLAN_SELECTED -> EXERCISE -> REST -> NEXT_EXERCISE -> COMPLETE` with pause, resume, and skip controls.
- **Visual & Audio HUD**:
  - Current exercise name, set $X$ of $Y$, rep progress, and routine progress bar.
  - Big rest countdown timer with audio announcements ("Rest, 60 seconds", 3-2-1 countdown, "Next up: ...").
  - Form cues prioritized so plan announcements never talk over live form-correction cues.

### 3. Claude-Powered Coach Chat & Post-Session Summaries (Feature 2)
- **Post-Session Performance Breakdown**: Summarizes completed vs. target reps, duration, average form score, tempo, and fatigue indicators.
- **Structured Claude Analysis**: Returns JSON containing personalized summary, wins, improvement focus areas, coach tips, and next-session recommendations via the Claude API (`POST /api/coach/summary`).
- **Interactive "Ask Your Coach" Box**: Ask questions on form, muscle soreness, or recovery via `POST /api/coach/chat`. Includes rate limiting (10 req/min), 500-character input caps, and safe non-diagnostic advice with medical disclaimers.
- **Graceful Offline Fallback**: Deterministic local rule-based generation if no API key is provided or network fails.

### 4. Adaptive Difficulty & Progression (Feature 3)
- **Live Form Tracking**: Detects when form drops late in a set (≥20% below early-rep baseline) or when fatigue slows rep tempo.
- **Mid-Set Advice**: Gives live voice and on-screen suggestions to finish early or lower the rep target.
- **Easy Finish Detection**: Rewards clean finishes with suggestions to increase reps or resistance next session.
- **Local Persistence**: Automatically saves progression adjustments to `data/progression.json`.

### 5. User Authentication Add-On
- **Login & Signup**: Tabbed authentication in `services/auth/login_wall.py` supporting user registration and login with salted PBKDF2-HMAC-SHA256 password hashing.
- **Session Persistence**: SQLite database (`data.db`) storing user credentials and exercise history.
- **Sign Out**: One-click Logout button in the sidebar.

---

## 🛠️ Architecture of New Modules

```
core/
  └── session_tracker.py       # Pure state machine runner (WorkoutRunner) & metrics aggregator (SessionTracker)
services/
  ├── workout_plans.py         # Data definitions for Fat Loss, Strength, and Beginner routines
  ├── adaptive.py              # Pure adaptive difficulty logic, fatigue detection, and progression persistence
  ├── coach_llm.py             # Anthropic Claude API client, prompt design, JSON validator, and rate limiter
  ├── api_server.py            # Tornado HTTP handlers for POST /api/coach/summary and POST /api/coach/chat
  ├── auth/login_wall.py       # Tabbed Login and Sign Up interface
  └── persistence/             # Database schema migrations and password hashing utilities
static/
  └── css/coach.css            # Dark theme styles for goal cards, rest timer, progress bar, and summary badges
tests/
  ├── conftest.py              # Isolated fixtures for webcam-free and network-free test execution
  ├── test_workout_runner.py   # State machine transitions, skips, pauses, and completions
  ├── test_adaptive.py         # Good set, late form drop, easy finish, and noisy data tests
  ├── test_coach_llm.py        # Claude JSON validation, fallbacks, input limits, and rate limiting
  ├── test_api_endpoints.py    # Tornado HTTP test cases for summary and chat endpoints
  └── test_auth.py             # Password hashing and authentication unit tests
```

---

## 📦 Setup & Installation

### 1. Clone & Setup Virtual Environment
```bash
git clone <repo-url>
cd "AIBuddy- Real time ai gym coach"

python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your credentials:
```ini
# Anthropic Claude API Key for Coach summaries and interactive chat
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Optional: configure Claude model (default: claude-3-7-sonnet-latest)
COACH_MODEL=claude-3-7-sonnet-latest

# Groq API Key for live rep and form-check voice cues
GROQ_API_KEY=your_groq_api_key_here
```
*(Note: If `ANTHROPIC_API_KEY` is omitted, the app will degrade gracefully to local rule-based coaching summaries).*

---

## 🏃 Running the Application

Start the Streamlit application:
```bash
streamlit run main.py
```
Open your browser at `http://localhost:8501`.

1. **Log in or Sign up** with your username and password.
2. In the sidebar:
   - Select **Free Workout** for standard single-exercise tracking.
   - Select **Guided Routine** for structured programs (Fat Loss, Strength, Beginner).
3. Allow camera access and begin your workout!

---

## 🧪 Running the Tests

The entire test suite runs without webcam or network access:
```bash
pytest tests/ -v
```
All 24 test cases cover:
- State machine runner transitions (`PLAN_SELECTED -> EXERCISE -> REST -> NEXT -> COMPLETE`)
- Adaptive difficulty decisions (good set, late form drop, easy finish, noisy data)
- Claude summary JSON validation and fallback mechanisms
- Interactive chat safeguards, input length limits, and per-IP rate limiting
- Tornado HTTP endpoints (`POST /api/coach/summary`, `POST /api/coach/chat`)
- Password hashing and user authentication

---

## 🔒 Security & Privacy
- **API Secrets**: Read exclusively via backend environment variables; never hardcoded and never exposed to the client.
- **Authentication**: Passwords are protected using salted PBKDF2-HMAC-SHA256 with 100,000 iterations.
- **Medical Disclaimer**: Coaching advice on pain or injury includes explicit disclaimers directing users to professional medical advice and never attempts to diagnose conditions.
