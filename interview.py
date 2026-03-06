import importlib
import os
import re
import time
from urllib.parse import unquote, urlparse

import streamlit as st

from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
)


ALLOWED_RETURN_HOSTS = {
    "qualtrics.com",
    "qsf.qualtrics.com",
    "lse.eu.qualtrics.com",
}


def is_allowed_return_url(url: str) -> bool:
    if not url:
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme != "https":
        return False

    hostname = (parsed.hostname or "").lower()

    if hostname == "qualtrics.com":
        return True
    if hostname.endswith(".qualtrics.com"):
        return True
    if hostname in ALLOWED_RETURN_HOSTS:
        return True

    return False


def build_return_url(return_base: str, llm_done: int, llm_status: str) -> str:
    sep = "&" if "?" in return_base else "?"
    return (
        f"{return_base}{sep}"
        f"llm_returning=1&llm_done={llm_done}&llm_status={llm_status}"
    )


def do_browser_redirect(url: str):
    st.markdown(
        f"""
        <script>
        window.top.location.href = {url!r};
        </script>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"[Click here if you are not redirected automatically]({url})")


def load_backup_messages(username: str, backups_directory: str):
    path = os.path.join(backups_directory, f"{username}_backup_transcript.txt")

    if not os.path.exists(path):
        return []

    messages = []

    try:
        with open(path, "r") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or ": " not in line:
                    continue

                role, content = line.split(": ", 1)

                if role in {"system", "user", "assistant"}:
                    messages.append({"role": role, "content": content})
    except Exception:
        return []

    return messages


def run_interview(config_module_name: str, default_username: str = "testaccount"):
    st.set_page_config(page_title="Interview", page_icon="🎓")

    config = importlib.import_module(config_module_name)

    def format_for_display(text: str, is_first_assistant: bool = False) -> str:
        display_text = text.replace("<m>", "").replace("</m>", "")

        if is_first_assistant:
            m = re.match(r"^\s*Hello[.!]?\s*(.*)$", display_text, flags=re.IGNORECASE | re.DOTALL)
            if m:
                rest = m.group(1)
                # Drop one immediate repeated greeting if present.
                rest = re.sub(r"^\s*Hello[.!]?\s*", "", rest, count=1, flags=re.IGNORECASE)
                display_text = "Hello!\n\n" + rest

        for phrase in getattr(config, "DISPLAY_BOLD_PHRASES", []):
            if phrase in display_text:
                display_text = display_text.replace(phrase, f"**{phrase}**")
        return display_text

    def save_backup():
        try:
            save_interview_data(
                username=st.session_state.username,
                transcripts_directory=config.BACKUPS_DIRECTORY,
                times_directory=config.BACKUPS_DIRECTORY,
                file_name_addition_transcript="_backup_transcript",
                file_name_addition_time="_backup_time",
            )
        except Exception:
            pass

    if "gpt" in config.MODEL.lower():
        api = "openai"
        from openai import OpenAI
    elif "claude" in config.MODEL.lower():
        api = "anthropic"
        import anthropic
    else:
        raise ValueError("Model must contain 'gpt' or 'claude'")

    raw_return_base = st.query_params.get("return_base", None)
    if raw_return_base is not None:
        return_base = unquote(str(raw_return_base).strip())
    else:
        return_base = None

    if config.LOGINS:
        pwd_correct, username = check_password()
        if not pwd_correct:
            st.stop()
        st.session_state.username = username
    else:
        respondent_id = st.query_params.get("id", None)

        if respondent_id is None:
            if "username" not in st.session_state:
                st.session_state.username = f"preview_{int(time.time())}"
            st.warning("Preview mode detected. Using temporary ID.")
            st.caption(f"Session ID: {st.session_state.username}")
        else:
            st.session_state.username = str(respondent_id).strip()

    os.makedirs(config.TRANSCRIPTS_DIRECTORY, exist_ok=True)
    os.makedirs(config.TIMES_DIRECTORY, exist_ok=True)
    os.makedirs(config.BACKUPS_DIRECTORY, exist_ok=True)

    if "interview_active" not in st.session_state:
        st.session_state.interview_active = True

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "return_base" not in st.session_state:
        st.session_state.return_base = return_base

    if "start_time" not in st.session_state:
        st.session_state.start_time = time.time()

    interview_previously_completed = check_if_interview_completed(
        config.TIMES_DIRECTORY,
        st.session_state.username,
    )

    if interview_previously_completed and not st.session_state.messages:
        st.session_state.interview_active = False
        st.markdown("Interview already completed.")

        if (
            st.session_state.return_base
            and is_allowed_return_url(st.session_state.return_base)
        ):
            completed_return_url = build_return_url(
                st.session_state.return_base,
                llm_done=1,
                llm_status="completed",
            )
            do_browser_redirect(completed_return_url)

        st.stop()

    if not st.session_state.messages:
        resumed_messages = load_backup_messages(
            st.session_state.username,
            config.BACKUPS_DIRECTORY,
        )
        if resumed_messages:
            st.session_state.messages = resumed_messages

    col1, col2 = st.columns([0.85, 0.15])

    with col2:
        if st.session_state.interview_active and st.button("Quit", help="End the interview."):
            st.session_state.interview_active = False

            quit_message = "You have cancelled the interview."
            st.session_state.messages.append({"role": "assistant", "content": quit_message})

            save_backup()

            if (
                st.session_state.return_base
                and is_allowed_return_url(st.session_state.return_base)
            ):
                quit_return_url = build_return_url(
                    st.session_state.return_base,
                    llm_done=1,
                    llm_status="quit",
                )
                do_browser_redirect(quit_return_url)
                st.stop()

    for i, message in enumerate(st.session_state.messages[1:], start=1):
        avatar = (
            config.AVATAR_INTERVIEWER
            if message["role"] == "assistant"
            else config.AVATAR_RESPONDENT
        )

        if not any(code in message["content"] for code in config.CLOSING_MESSAGES.keys()):
            with st.chat_message(message["role"], avatar=avatar):
                is_first_assistant = i == 1 and message["role"] == "assistant"
                display_text = format_for_display(
                    message["content"],
                    is_first_assistant=is_first_assistant,
                )
                st.markdown(display_text)

    if api == "openai":
        client = OpenAI(api_key=st.secrets["API_KEY_OPENAI"])
    else:
        client = anthropic.Anthropic(api_key=st.secrets["API_KEY_ANTHROPIC"])

    def build_api_kwargs():
        if api == "openai":
            api_kwargs = {"stream": True}
        else:
            api_kwargs = {"system": config.SYSTEM_PROMPT}

        api_kwargs["messages"] = st.session_state.messages
        api_kwargs["model"] = config.MODEL
        api_kwargs["max_tokens"] = config.MAX_OUTPUT_TOKENS

        if config.TEMPERATURE is not None:
            api_kwargs["temperature"] = config.TEMPERATURE

        return api_kwargs

    if not st.session_state.messages:
        if api == "openai":
            st.session_state.messages.append(
                {"role": "system", "content": config.SYSTEM_PROMPT}
            )

            with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
                message_placeholder = st.empty()
                message_interviewer = ""
                stream = client.chat.completions.create(**build_api_kwargs())

                for message in stream:
                    text_delta = message.choices[0].delta.content

                    if text_delta:
                        message_interviewer += text_delta

                    display_text = format_for_display(
                        message_interviewer,
                        is_first_assistant=True,
                    )
                    message_placeholder.markdown(display_text + "▌")

                display_text = format_for_display(
                    message_interviewer,
                    is_first_assistant=True,
                )
                message_placeholder.markdown(display_text)

        else:
            st.session_state.messages.append({"role": "user", "content": "Hi"})

            with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
                message_placeholder = st.empty()
                message_interviewer = ""

                with client.messages.stream(**build_api_kwargs()) as stream:
                    for text_delta in stream.text_stream:
                        if text_delta:
                            message_interviewer += text_delta

                        display_text = format_for_display(message_interviewer)
                        message_placeholder.markdown(display_text + "▌")

                display_text = format_for_display(message_interviewer)
                message_placeholder.markdown(display_text)

        st.session_state.messages.append(
            {"role": "assistant", "content": message_interviewer}
        )

        save_backup()

    if st.session_state.interview_active:
        if message_respondent := st.chat_input("Your message here"):
            st.session_state.messages.append(
                {"role": "user", "content": message_respondent}
            )

            save_backup()

            with st.chat_message("user", avatar=config.AVATAR_RESPONDENT):
                st.markdown(message_respondent)

            with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
                message_placeholder = st.empty()
                message_interviewer = ""

                if api == "openai":
                    stream = client.chat.completions.create(**build_api_kwargs())

                    for message in stream:
                        text_delta = message.choices[0].delta.content

                        if text_delta:
                            message_interviewer += text_delta

                        if len(message_interviewer) > 5:
                            display_text = format_for_display(message_interviewer)
                            message_placeholder.markdown(display_text + "▌")

                        if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                            message_placeholder.empty()
                            break

                else:
                    with client.messages.stream(**build_api_kwargs()) as stream:
                        for text_delta in stream.text_stream:
                            if text_delta:
                                message_interviewer += text_delta

                            if len(message_interviewer) > 5:
                                display_text = format_for_display(message_interviewer)
                                message_placeholder.markdown(display_text + "▌")

                            if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                                message_placeholder.empty()
                                break

                if not any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                    display_text = format_for_display(message_interviewer)
                    message_placeholder.markdown(display_text)

                    st.session_state.messages.append(
                        {"role": "assistant", "content": message_interviewer}
                    )
                    save_backup()

                for code in config.CLOSING_MESSAGES.keys():
                    if code in message_interviewer:
                        st.session_state.interview_active = False

                        closing_message = config.CLOSING_MESSAGES[code]

                        st.markdown(closing_message)

                        st.session_state.messages.append(
                            {"role": "assistant", "content": closing_message}
                        )

                        max_attempts = 30
                        attempt = 0
                        completed = False

                        while not completed and attempt < max_attempts:
                            save_interview_data(
                                username=st.session_state.username,
                                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                                times_directory=config.TIMES_DIRECTORY,
                            )

                            completed = check_if_interview_completed(
                                config.TIMES_DIRECTORY,
                                st.session_state.username,
                            )

                            attempt += 1
                            time.sleep(0.1)

                        if (
                            st.session_state.return_base
                            and is_allowed_return_url(st.session_state.return_base)
                        ):
                            completed_return_url = build_return_url(
                                st.session_state.return_base,
                                llm_done=1,
                                llm_status="completed",
                            )
                            do_browser_redirect(completed_return_url)

                        st.stop()
