import streamlit as st
import os
import time
import pandas as pd
import requests
from services.auth.login_wall import render_login_wall
from services.state.session_defaults import initial_session_defaults
from services.config.workout_config import EXERCISE_OPTIONS
from services.ui.style_loader import load_css, inject_local_font, inject_webrtc_styles
from services.persistence.exercise_repository import init_db
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from services.vision.exercise_video_processor import VideoProcessorClass
from services.tracking.metrics import sync_metrics_update
from services.persistence.exercise_repository import get_users_exercises
from groq import Groq
from services.coaching.llm import LLMCoach
from services.coaching.tts import TextToSpeech
from services.coaching.voice_pipeline import VoicePipeline, autoplay_audio


def get_ice_servers():
    selected_mode = st.session_state.get("webrtc_ice_mode", "Default (STUN + Metered TURN)")
    
    # Base fallback is always Google STUN
    ice_servers = [{"urls": ["stun:stun.l.google.com:19302"]}]
    
    if selected_mode == "Default (STUN + Metered TURN)":
        ice_servers.extend([
            {"urls": ["stun:stun1.l.google.com:19302"]},
            {"urls": ["stun:stun2.l.google.com:19302"]},
            {
                "urls": [
                    "turn:openrelay.metered.ca:80",
                    "turn:openrelay.metered.ca:443",
                    "turn:openrelay.metered.ca:443?transport=tcp",
                ],
                "username": "openrelayproject",
                "credential": "openrelayproject",
            }
        ])
    elif selected_mode == "Google STUN Only":
        ice_servers.extend([
            {"urls": ["stun:stun1.l.google.com:19302"]},
            {"urls": ["stun:stun2.l.google.com:19302"]}
        ])
    elif selected_mode == "Twilio TURN (Recommended)":
        sid = st.session_state.get("twilio_sid", "")
        token = st.session_state.get("twilio_token", "")
        if sid and token:
            try:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Tokens.json"
                response = requests.post(url, auth=(sid, token), timeout=5)
                if response.status_code == 201:
                    fetched_servers = response.json().get("ice_servers", [])
                    if fetched_servers:
                        return fetched_servers
                else:
                    st.sidebar.error(f"Twilio API Error: {response.status_code}")
            except Exception as e:
                st.sidebar.error(f"Connection to Twilio failed: {e}")
        # If Twilio fails or is empty, return STUN servers
        ice_servers.extend([
            {"urls": ["stun:stun1.l.google.com:19302"]},
            {"urls": ["stun:stun2.l.google.com:19302"]}
        ])
    elif selected_mode == "Custom TURN Server":
        c_url = st.session_state.get("custom_turn_url", "")
        c_user = st.session_state.get("custom_turn_username", "")
        c_pass = st.session_state.get("custom_turn_password", "")
        if c_url:
            server_dict = {"urls": [c_url]}
            if c_user:
                server_dict["username"] = c_user
            if c_pass:
                server_dict["credential"] = c_pass
            ice_servers.append(server_dict)
            
    return ice_servers


def main():
    st.set_page_config(
        page_icon="🏋️‍♀️",
        page_title="AI Real-time GYM Coach",
        initial_sidebar_state="expanded",
        layout="centered"
    )

    # Use __file__-relative path so CSS is found regardless of cwd
    _app_dir = os.path.dirname(os.path.abspath(__file__))
    load_css(os.path.join(_app_dir, "static", "style.css"))
    # AdobeClean.otf removed — now using Inter (Google Fonts) defined in style.css

    init_db()

    if not render_login_wall():
        return 

    initial_session_defaults()

    if "voice_pipeline" not in st.session_state:
        try:
            api_key = os.environ.get("GROQ_API_KEY", "")

            if not api_key and hasattr(st, "secrets") and "GROQ_API_KEY" in st.secrets:
                api_key = st.secrets["GROQ_API_KEY"]
            
            groq_client = Groq(api_key=api_key)
            llm_coach = LLMCoach(groq_client)
            tts = TextToSpeech()
            st.session_state.voice_pipeline = VoicePipeline(llm_coach, tts)
        except Exception as e:
            st.session_state.voice_pipeline = None

    workout_started = st.session_state.get("workout_started", False)
    
    with st.sidebar:
        st.title("🏋️‍♂️ Apna AI Coach")

        if st.session_state.get("groq_api_error"):
            st.error("⚠️ **AI Voice Coaching Disabled**\nThe Groq API Key is invalid or missing. Posture correction and rep tracking will still work normally.")
            st.divider()

        if st.session_state.username:
            st.caption(f"👤 Login as {st.session_state.username}")

        st.divider()

        st.subheader("Workout Plan")

        if not workout_started:
            plan_exercise = st.selectbox("Exercise", options=EXERCISE_OPTIONS, key="plan_exercise")

            plan_sets = st.number_input("Sets", min_value=0, max_value=50, key="plan_sets", step=1)

            plan_reps = st.number_input("Reps per Set", min_value=0, max_value=50, key="plan_reps", step=1)

            st.markdown("")

            start_session_button = st.button("Start Workout", width="stretch", key="start_session_button")

            if start_session_button:
                st.session_state.exercise_type = plan_exercise
                st.session_state.target_sets = int(plan_sets)
                st.session_state.reps_per_set = int(plan_reps)
                st.session_state.reps = 0
                st.session_state.workout_started = True
                st.session_state.set_cycle_started_at = time.time()
                st.session_state.last_saved_sets_completed = 0

                if st.session_state.voice_pipeline:
                    result = st.session_state.voice_pipeline.process_event(
                        event="workout_started",
                        exercise=plan_exercise,
                        metrics={}
                    )
                    
                    if result:
                        st.session_state.audio_to_play, st.session_state.coach_feedback = result

                st.session_state.last_notified_sets_completed = 0
                st.session_state.last_notified_workout_complete = False
                st.rerun()
        else:
            exercise = st.session_state.get("exercise_type")
            sets = st.session_state.get("target_sets")
            reps = st.session_state.get("reps_per_set")

            st.info(f"**{exercise}** -- {sets} Sets / {reps} Reps")

            end_session_button = st.button("End Workout", key="end_session_button", width="stretch")

            if end_session_button:
                st.session_state.workout_started = False
                
                if st.session_state.voice_pipeline:
                    result = st.session_state.voice_pipeline.process_event(
                        event="workout_completed",
                        exercise=exercise,
                        metrics={}
                    )
                    if result:
                        st.session_state.audio_to_play, st.session_state.coach_feedback = result

                st.rerun()

        if workout_started:
            st.divider()

            exercise = st.session_state.get("exercise_type")
            total_reps = st.session_state.get("reps")
            current_set_reps = st.session_state.get("current_set_reps")
            reps_per_set = st.session_state.get("reps_per_set")
            sets_completed = st.session_state.get("sets_completed")
            target_sets = st.session_state.get("target_sets")

            st.subheader("Progress")

            st.metric("Total Reps", f"{total_reps}")
            st.metric("Current Set Reps", f"{current_set_reps} / {reps_per_set}")
            st.metric("Sets Completed", f"{sets_completed} / {target_sets}")

            st.divider()

            if exercise == "Squats":
                st.subheader("Squat Metrics")
                st.metric("Knee Angle", f"{st.session_state.knee_angle}°")
                st.metric("Back Angle", f"{st.session_state.back_angle}°")
                st.metric("Depth Status", st.session_state.depth_status)

            elif exercise == "Push-ups":
                st.subheader("Push-up Metrics")
                st.metric("Elbow Angle", f"{st.session_state.elbow_angle}°")
                st.metric("Body Alignment", st.session_state.body_alignment)
                st.metric("Hip Position", st.session_state.hip_status)

            elif exercise == "Biceps Curls (Dumbbell)":
                st.subheader("Curl Metrics")
                st.metric("Elbow Angle", f"{st.session_state.elbow_angle}°")
                st.metric("Shoulder Stability", st.session_state.shoulder_status)
                st.metric("Swing Detection", st.session_state.swing_status)

            elif exercise == "Shoulder Press":
                st.subheader("Shoulder Press Metrics")
                st.metric("Elbow Angle", f"{st.session_state.elbow_angle}°")
                st.metric("Arm Extension", st.session_state.extension_status)
                st.metric("Back Arch", st.session_state.back_arch_status)

            elif exercise == "Lunges":
                st.subheader("Lunge Metrics")
                st.metric("Front Knee Angle", f"{st.session_state.front_knee_angle}°")
                st.metric("Torso Angle", f"{st.session_state.torso_angle}°")
                st.metric("Balance Status", st.session_state.balance_status)

        # WebRTC Connection Settings
        st.divider()
        with st.expander("🌐 WebRTC Connection Settings"):
            # Check if running on HF Space and no Twilio env, show warning/guidance
            if "SPACE_ID" in os.environ and not (os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN")):
                st.warning(
                    "⚠️ **WebRTC Notice: Running on Hugging Face Spaces**\n\n"
                    "WebRTC camera connections often time out inside Hugging Face iframes due to strict firewalls. "
                    "To fix this permanently, please add your `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` to your **Hugging Face Space Secrets** (Settings > Variables and secrets)."
                )

            st.markdown(
                """
                If your webcam is taking too long to connect, select a different server configuration.
                """
            )
            
            # Check if Twilio env is available
            has_twilio_env = bool(os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN"))
            
            # Determine default index
            mode_options = [
                "Default (STUN + Metered TURN)",
                "Google STUN Only",
                "Twilio TURN (Recommended)",
                "Custom TURN Server"
            ]
            default_mode = "Twilio TURN (Recommended)" if has_twilio_env else "Default (STUN + Metered TURN)"
            
            ice_mode = st.selectbox(
                "Connection Mode",
                options=mode_options,
                index=mode_options.index(default_mode),
                key="webrtc_ice_mode"
            )
            
            if ice_mode == "Twilio TURN (Recommended)":
                st.markdown(
                    "[Get a free Twilio Account](https://www.twilio.com/try-twilio)"
                )
                twilio_sid = st.text_input(
                    "Twilio Account SID",
                    value=os.environ.get("TWILIO_ACCOUNT_SID", st.session_state.get("twilio_sid", "")),
                    key="twilio_sid_input"
                )
                twilio_token = st.text_input(
                    "Twilio Auth Token",
                    value=os.environ.get("TWILIO_AUTH_TOKEN", st.session_state.get("twilio_token", "")),
                    type="password",
                    key="twilio_token_input"
                )
                
                st.session_state.twilio_sid = twilio_sid
                st.session_state.twilio_token = twilio_token

            elif ice_mode == "Custom TURN Server":
                custom_url = st.text_input(
                    "TURN URL",
                    value=st.session_state.get("custom_turn_url", ""),
                    placeholder="turn:example.com:3478",
                    key="custom_turn_url_input"
                )
                custom_username = st.text_input(
                    "Username",
                    value=st.session_state.get("custom_turn_username", ""),
                    key="custom_turn_username_input"
                )
                custom_password = st.text_input(
                    "Password/Credential",
                    value=st.session_state.get("custom_turn_password", ""),
                    type="password",
                    key="custom_turn_password_input"
                )
                
                st.session_state.custom_turn_url = custom_url
                st.session_state.custom_turn_username = custom_username
                st.session_state.custom_turn_password = custom_password

    st.title("AI Real-time GYM Coach")
    st.markdown("#### Real-time pose detection with proactive AI voice coaching")
    
    # Show dynamic direct URL banner if running inside HF Spaces iframe
    if "SPACE_ID" in os.environ:
        st.markdown(
            """
            <div style="background-color: #1e293b; border-left: 5px solid #3b82f6; padding: 12px 16px; border-radius: 4px; margin-bottom: 20px;">
                <strong>🌐 Hugging Face Space User:</strong> If your camera gets stuck loading or shows network connection warnings, open the app in 
                <a href="https://arunsingh225-ai-gym-coach.hf.space" target="_blank" style="color: #60a5fa; text-decoration: underline; font-weight: bold;">Direct Fullscreen Mode</a> 
                to bypass iframe security restrictions.
            </div>
            """,
            unsafe_allow_html=True
        )
 
    if st.session_state.get("audio_to_play"):
        autoplay_audio(st.session_state.audio_to_play)

    if st.session_state.get("coach_feedback"):
        st.markdown("")
        st.success(f"🤖 **Coach:** {st.session_state.coach_feedback}")

    if not workout_started:
        st.markdown(
            """
            <div style="
                border: 10px dashed #444;
                border-radius: 0px;
                padding: 48px 32px;
                text-align: center;
                color: #888;
                margin-top: 32px;
                margin-bottom: 32px;
            ">
                <h2 style="color:#ccc; margin-bottom:8px;">👈 Set your workout plan</h2>
                <p style="font-size:1.05rem;">
                    Choose your exercise, sets and reps in the sidebar,<br>
                    then click <strong>Start Workout</strong> to activate the camera and AI coach.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        # Show direct fullscreen link notice to bypass iframe WebRTC blocks on Hugging Face Spaces
        if "SPACE_ID" in os.environ:
            st.info(
                "🌐 **Webcam Stuck loading?** If the connection times out or fails, please open the app in "
                "[Direct Fullscreen Mode](https://arunsingh225-ai-gym-coach.hf.space) to bypass browser iframe sandbox restrictions."
            )

        ice_servers = get_ice_servers()

        context = webrtc_streamer(
            key="exercise-analysis",
            mode=WebRtcMode.SENDRECV,
            video_processor_factory=VideoProcessorClass,
            rtc_configuration={"iceServers": ice_servers},
            media_stream_constraints={
                "video": True,
                "audio": False
            },
            async_processing=True
        )

        sync_metrics_update(context)

        if context.state.playing:
            time.sleep(0.25)
            st.rerun()

        inject_webrtc_styles()

    st.divider()

    st.markdown("#### Workout History")

    user_id = st.session_state.get("user_id", 0)

    if isinstance(user_id, int):
        history_rows = get_users_exercises(user_id)

        arr = [
            {
                "Exercise": row['exercise_name'],
                "Reps": row['reps'],
                "Sets": row['sets'],
                "Time (sec)": row['time'],
                "Date": row['created_at']
            }
            for row in history_rows
        ]

        df = pd.DataFrame(arr)

        if not df.empty:
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            agg_df = df.groupby(["Exercise", "Date"]).agg({
                "Reps": 'sum',
                "Sets": "sum",
                "Time (sec)": "sum"
            }).reset_index()
            agg_df.index += 1
            st.table(agg_df, border="horizontal")
        else:
            st.info("No workout history found.")


if __name__ == "__main__":
    main()
    