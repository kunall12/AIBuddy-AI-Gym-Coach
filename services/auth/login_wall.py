import streamlit as st
from services.persistence.exercise_repository import (
    get_user,
    get_or_create_user,
    create_user_with_password,
    authenticate_user,
)


def render_login_wall():
    if st.session_state.get("user_id") is not None:
        return True
    
    st.markdown(
        """
        <div class="auth-hero-card">
            <div class="auth-brand-badge">⚡ AIBUDDY PRO</div>
            <h1 class="auth-brand-title">Elevate Your Training</h1>
            <p class="auth-brand-subtitle">Real-time computer vision pose tracking, automated rep counting & AI voice feedback</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_tab, signup_tab = st.tabs(["🔑 Log In", "📝 Sign Up"])

    with login_tab:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="e.g. alex_fitness", key="login_username")
            password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")
            submit_button = st.form_submit_button("Log In", use_container_width=True)

        if submit_button:
            if not username.strip():
                st.error("Please enter your username.")
                return False
            
            user = authenticate_user(username.strip(), password)
            if user:
                st.session_state["user_id"] = user["id"]
                st.session_state["username"] = user["username"]
                st.success(f"Welcome back, {user['username']}!")
                st.rerun()
            else:
                existing = get_user(username.strip())
                if not existing:
                    st.error("User not found. Please sign up first.")
                else:
                    st.error("Invalid password. Please try again.")

    with signup_tab:
        with st.form("signup_form", clear_on_submit=False):
            new_username = st.text_input("Choose Username", placeholder="e.g. alex_fitness", key="signup_username")
            new_password = st.text_input("Create Password", type="password", placeholder="At least 4 characters", key="signup_password")
            confirm_password = st.text_input("Confirm Password", type="password", placeholder="Re-enter your password", key="signup_confirm_password")
            signup_button = st.form_submit_button("Create Account", use_container_width=True)

        if signup_button:
            clean_username = new_username.strip()
            if not clean_username:
                st.error("Username cannot be empty.")
                return False
            if len(new_password) < 4:
                st.error("Password must be at least 4 characters long.")
                return False
            if new_password != confirm_password:
                st.error("Passwords do not match.")
                return False

            existing = get_user(clean_username)
            if existing:
                st.error("Username already taken. Please choose another or log in.")
                return False

            user = create_user_with_password(clean_username, new_password)
            st.session_state["user_id"] = user["id"]
            st.session_state["username"] = user["username"]
            st.success("Account created successfully!")
            st.rerun()

    return False
