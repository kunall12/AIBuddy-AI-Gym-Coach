"""Workout plan definitions for AIBuddy Guided Coaching.

Plans are purely data-driven. Adding new goals or routines is accomplished
by adding entries to WORKOUT_PLANS without modifying runner logic.

Constraint: Exercises must strictly match detectors supported by AIBuddy:
- "Squats"
- "Push-ups"
- "Biceps Curls (Dumbbell)"
- "Shoulder Press"
- "Lunges"

Where a goal typically includes unsupported exercises (e.g. Bench Press,
Deadlifts, Burpees), biomechanically appropriate supported exercises are
substituted with transparent notes in the plan metadata.
"""

from typing import Any, Dict, List, Optional


WORKOUT_PLANS: Dict[str, Dict[str, Any]] = {
    "fat_loss": {
        "id": "fat_loss",
        "name": "Fat Loss & Metabolic Conditioning",
        "goal": "Fat Loss",
        "description": "High-density full-body circuit maximizing caloric expenditure and cardiovascular output.",
        "difficulty": "Intermediate",
        "estimated_duration_min": 20,
        "exercises": [
            {
                "exercise_name": "Squats",
                "sets": 3,
                "reps": 15,
                "rest_seconds": 30,
                "form_cue": "Drive through heels, keep chest high, and maintain an energetic cadence.",
                "substitution_note": None,
            },
            {
                "exercise_name": "Push-ups",
                "sets": 3,
                "reps": 12,
                "rest_seconds": 30,
                "form_cue": "Keep a rigid plank line and avoid sagging hips as you push.",
                "substitution_note": "Substituted for Burpees to allow continuous pose-tracking.",
            },
            {
                "exercise_name": "Lunges",
                "sets": 3,
                "reps": 12,
                "rest_seconds": 30,
                "form_cue": "Step deep, bend both knees toward 90 degrees, and stay balanced.",
                "substitution_note": "Substituted for Jump Lunges for joint-safe rep detection.",
            },
            {
                "exercise_name": "Shoulder Press",
                "sets": 3,
                "reps": 12,
                "rest_seconds": 45,
                "form_cue": "Brace core firmly and press overhead without leaning back.",
                "substitution_note": "Substituted for Kettlebell Thrusters.",
            },
        ],
    },
    "strength": {
        "id": "strength",
        "name": "Strength & Muscle Hypertrophy",
        "goal": "Strength",
        "description": "Focused resistance routine emphasizing mechanical tension, full range of motion, and ample rest.",
        "difficulty": "Advanced",
        "estimated_duration_min": 30,
        "exercises": [
            {
                "exercise_name": "Squats",
                "sets": 4,
                "reps": 8,
                "rest_seconds": 75,
                "form_cue": "Sink to parallel depth, pause momentarily, and explode upward.",
                "substitution_note": "Substituted for Barbell Back Squats.",
            },
            {
                "exercise_name": "Push-ups",
                "sets": 4,
                "reps": 8,
                "rest_seconds": 60,
                "form_cue": "Control a 2-second eccentric descent with elbows tucked at 45 degrees.",
                "substitution_note": "Substituted for Flat Barbell Bench Press.",
            },
            {
                "exercise_name": "Shoulder Press",
                "sets": 4,
                "reps": 8,
                "rest_seconds": 60,
                "form_cue": "Press straight up to lockout while keeping glutes and abs locked.",
                "substitution_note": "Substituted for Standing Overhead Barbell Press.",
            },
            {
                "exercise_name": "Biceps Curls (Dumbbell)",
                "sets": 3,
                "reps": 10,
                "rest_seconds": 60,
                "form_cue": "Pin elbows to ribs and squeeze biceps firmly at the top.",
                "substitution_note": "Substituted for Heavy Barbell Curl.",
            },
        ],
    },
    "beginner": {
        "id": "beginner",
        "name": "Beginner Foundations",
        "goal": "Beginner",
        "description": "Gentle intro routine building foundational movement patterns, postural alignment, and motor control.",
        "difficulty": "Beginner",
        "estimated_duration_min": 15,
        "exercises": [
            {
                "exercise_name": "Squats",
                "sets": 2,
                "reps": 8,
                "rest_seconds": 60,
                "form_cue": "Lower down slowly as if sitting in a chair, keeping feet flat.",
                "substitution_note": None,
            },
            {
                "exercise_name": "Push-ups",
                "sets": 2,
                "reps": 6,
                "rest_seconds": 60,
                "form_cue": "Keep whole body straight. Go at a comfortable, steady pace.",
                "substitution_note": None,
            },
            {
                "exercise_name": "Lunges",
                "sets": 2,
                "reps": 8,
                "rest_seconds": 60,
                "form_cue": "Focus on stability. Step forward comfortably without rushing.",
                "substitution_note": "Substituted for Split Squats for easier balance pacing.",
            },
            {
                "exercise_name": "Biceps Curls (Dumbbell)",
                "sets": 2,
                "reps": 8,
                "rest_seconds": 45,
                "form_cue": "Stand tall, relax shoulders, and avoid swinging your back.",
                "substitution_note": None,
            },
        ],
    },
}


def get_all_plans() -> Dict[str, Dict[str, Any]]:
    """Return dictionary of all available workout plans."""
    return WORKOUT_PLANS


def get_plan_by_id(plan_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a specific plan by its ID."""
    return WORKOUT_PLANS.get(plan_id)


def get_plan_by_goal(goal_name: str) -> Optional[Dict[str, Any]]:
    """Retrieve the first matching plan for a goal name (case-insensitive)."""
    normalized = goal_name.strip().lower()
    for plan in WORKOUT_PLANS.values():
        if plan["goal"].lower() == normalized or plan["id"].lower() == normalized:
            return plan
    return None


def get_supported_goals() -> List[str]:
    """Return a unique ordered list of supported goal names."""
    seen = set()
    goals = []
    for plan in WORKOUT_PLANS.values():
        goal = plan["goal"]
        if goal not in seen:
            seen.add(goal)
            goals.append(goal)
    return goals
