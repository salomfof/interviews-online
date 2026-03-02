#HOW TO Run
#cd "/Users/salome/Dropbox/Research/Work with Kate Smith/AI Interview/interviews-main/code"
#conda activate interviews
#streamlit run interview.py

import streamlit as st
import time
import os
import importlib
from urllib.parse import unquote

from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
)

# Set page title and icon (generic for landing + interview)
st.set_page_config(page_title="Interview", page_icon="🎓")

# Choose prompt group from URL (default latent)
raw_group = st.query_params.get("group", None)
if raw_group is None:
    st.title("Interview Links")
    st.write("Choose the interview group to start:")
    st.link_button("Latent interview", "?group=latent")
    st.link_button("Leavers interview", "?group=leavers")
    st.link_button("Entrepreneurs interview", "?group=entrepreneurs")
    st.stop()

group = str(raw_group).strip().lower()

CONFIG_BY_GROUP = {
    "latent": "config_latent",
    "leavers": "config_leavers",
    "entrepreneurs": "config_entrepreneurs",
}

if group not in CONFIG_BY_GROUP:
    raise ValueError(
        f"Unknown group='{group}'. Use one of: latent, leavers, entrepreneurs."
    )

selected_module = CONFIG_BY_GROUP[group]
config = importlib.import_module(selected_module)

# Load API library
if "gpt" in config.MODEL.lower():
    api = "openai"
    from openai import OpenAI
elif "claude" in config.MODEL.lower():
    api = "anthropic"
    import anthropic
else:
    raise ValueError("Model does not contain 'gpt' or 'claude'; unable to determine API.")

# Read return URL passed by Qualtrics
raw_return_url = st.query_params.get("return", None)
if raw_return_url is not None:
    return_url = unquote(str(raw_return_url).strip())
else:
    return_url = None

# Restrict where you allow redirects
ALLOWED_RETURN_HOSTS = ["qualtrics.com", "qsf.qualtrics.com", "lse.eu.qualtrics.com"]

def is_allowed_return_url(url: str) -> bool:
    if not url:
        return False
    url_l = url.lower()
    return any(host in url_l for host in ALLOWED_RETURN_HOSTS)

def do_browser_redirect(url: str):
    st.markdown(
        f"""
        <script>
          window.top.location.href = {url!r};
        </script>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"If you are not redirected automatically, click here: {url}")

# Check if usernames and logins are enabled
if config.LOGINS:
    pwd_correct, username = check_password()
    if not pwd_correct:
        st.stop()
    else:
        st.session_state.username = username
else:
    respondent_id = st.query_params.get("id", None)
    if respondent_id is None:
        st.session_state.username = f"testaccount_{group}"
    else:
        st.session_state.username = str(respondent_id).strip()

# Create directories if they do not already exist
if not os.path.exists(config.TRANSCRIPTS_DIRECTORY):
    os.makedirs(config.TRANSCRIPTS_DIRECTORY)
if not os.path.exists(config.TIMES_DIRECTORY):
    os.makedirs(config.TIMES_DIRECTORY)
if not os.path.exists(config.BACKUPS_DIRECTORY):
    os.makedirs(config.BACKUPS_DIRECTORY)

# Initialise session state
if "interview_active" not in st.session_state:
    st.session_state.interview_active = True

if "messages" not in st.session_state:
    st.session_state.messages = []

if "return_url" not in st.session_state:
    st.session_state.return_url = return_url

if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
    st.session_state.start_time_file_names = time.strftime(
        "%Y_%m_%d_%H_%M_%S", time.localtime(st.session_state.start_time)
    )

# Check if interview previously completed
interview_previously_completed = check_if_interview_completed(
    config.TIMES_DIRECTORY, st.session_state.username
)

# If app started but interview was previously completed
if interview_previously_completed and not st.session_state.messages:
    st.session_state.interview_active = False
    completed_message = "Interview already completed."
    st.markdown(completed_message)

# Add Quit button
col1, col2 = st.columns([0.85, 0.15])
with col2:
    if st.session_state.interview_active and st.button("Quit", help="End the interview."):
        st.session_state.interview_active = False
        quit_message = "You have cancelled the interview."
        st.session_state.messages.append({"role": "assistant", "content": quit_message})
        save_interview_data(
            st.session_state.username,
            config.TRANSCRIPTS_DIRECTORY,
            config.TIMES_DIRECTORY,
        )

        if st.session_state.return_url and is_allowed_return_url(st.session_state.return_url):
            do_browser_redirect(st.session_state.return_url)
            st.stop()

# Display previous conversation (except system prompt or first message)
for message in st.session_state.messages[1:]:
    if message["role"] == "assistant":
        avatar = config.AVATAR_INTERVIEWER
    else:
        avatar = config.AVATAR_RESPONDENT

    if not any(code in message["content"] for code in config.CLOSING_MESSAGES.keys()):
        with st.chat_message(message["role"], avatar=avatar):
            display_text = message["content"].replace("<m>", "").replace("</m>", "")
            st.markdown(display_text)

# Load API client
if api == "openai":
    client = OpenAI(api_key=st.secrets["API_KEY_OPENAI"])
    api_kwargs = {"stream": True}
elif api == "anthropic":
    client = anthropic.Anthropic(api_key=st.secrets["API_KEY_ANTHROPIC"])
    api_kwargs = {"system": config.SYSTEM_PROMPT}
else:
    raise ValueError("Unknown API type.")

# API kwargs
api_kwargs["messages"] = st.session_state.messages
api_kwargs["model"] = config.MODEL
api_kwargs["max_tokens"] = config.MAX_OUTPUT_TOKENS
if config.TEMPERATURE is not None:
    api_kwargs["temperature"] = config.TEMPERATURE

# If interview history is empty, add system prompt and get first message
if not st.session_state.messages:
    if api == "openai":
        st.session_state.messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            stream = client.chat.completions.create(**api_kwargs)
            message_interviewer = st.write_stream(stream)

    elif api == "anthropic":
        st.session_state.messages.append({"role": "user", "content": "Hi"})
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            message_placeholder = st.empty()
            message_interviewer = ""
            with client.messages.stream(**api_kwargs) as stream:
                for text_delta in stream.text_stream:
                    if text_delta is not None:
                        message_interviewer += text_delta
                    display_text = message_interviewer.replace("<m>", "").replace("</m>", "")
                    message_placeholder.markdown(display_text + "▌")
            display_text = message_interviewer.replace("<m>", "").replace("</m>", "")
            message_placeholder.markdown(display_text)

    st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

    # Store first backup files
    save_interview_data(
        username=st.session_state.username,
        transcripts_directory=config.BACKUPS_DIRECTORY,
        times_directory=config.BACKUPS_DIRECTORY,
        file_name_addition_transcript=f"_transcript_started_{st.session_state.start_time_file_names}",
        file_name_addition_time=f"_time_started_{st.session_state.start_time_file_names}",
    )

# Main chat if interview is active
if st.session_state.interview_active:
    if message_respondent := st.chat_input("Your message here"):
        st.session_state.messages.append({"role": "user", "content": message_respondent})

        with st.chat_message("user", avatar=config.AVATAR_RESPONDENT):
            st.markdown(message_respondent)

        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            message_placeholder = st.empty()
            message_interviewer = ""

            if api == "openai":
                stream = client.chat.completions.create(**api_kwargs)
                for message in stream:
                    text_delta = message.choices[0].delta.content
                    if text_delta is not None:
                        message_interviewer += text_delta

                    if len(message_interviewer) > 5:
                        display_text = message_interviewer.replace("<m>", "").replace("</m>", "")
                        message_placeholder.markdown(display_text + "▌")

                    if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                        message_placeholder.empty()
                        break

            elif api == "anthropic":
                with client.messages.stream(**api_kwargs) as stream:
                    for text_delta in stream.text_stream:
                        if text_delta is not None:
                            message_interviewer += text_delta

                        if len(message_interviewer) > 5:
                            display_text = message_interviewer.replace("<m>", "").replace("</m>", "")
                            message_placeholder.markdown(display_text + "▌")

                        if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                            message_placeholder.empty()
                            break

            # If no closing code, display and store the message
            if not any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                display_text = message_interviewer.replace("<m>", "").replace("</m>", "")
                message_placeholder.markdown(display_text)
                st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

                try:
                    save_interview_data(
                        username=st.session_state.username,
                        transcripts_directory=config.BACKUPS_DIRECTORY,
                        times_directory=config.BACKUPS_DIRECTORY,
                        file_name_addition_transcript=f"_transcript_started_{st.session_state.start_time_file_names}",
                        file_name_addition_time=f"_time_started_{st.session_state.start_time_file_names}",
                    )
                except:
                    pass

            # If closing code, show closing message, save, then redirect back
            for code in config.CLOSING_MESSAGES.keys():
                if code in message_interviewer:
                    st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

                    st.session_state.interview_active = False
                    closing_message = config.CLOSING_MESSAGES[code]
                    st.markdown(closing_message)
                    st.session_state.messages.append({"role": "assistant", "content": closing_message})

                    final_transcript_stored = False
                    while final_transcript_stored is False:
                        save_interview_data(
                            username=st.session_state.username,
                            transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                            times_directory=config.TIMES_DIRECTORY,
                        )
                        final_transcript_stored = check_if_interview_completed(
                            config.TRANSCRIPTS_DIRECTORY, st.session_state.username
                        )
                        time.sleep(0.1)

                    if st.session_state.return_url and is_allowed_return_url(st.session_state.return_url):
                        do_browser_redirect(st.session_state.return_url)
                        st.stop()
