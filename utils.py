import streamlit as st
import hmac
import time
import os
import io

# Azure Blob Storage
from azure.storage.blob import BlobServiceClient


def get_blob_service_client():
    """Return a BlobServiceClient using the connection string from secrets."""
    conn_str = os.environ.get(
        "AZURE_STORAGE_CONNECTION_STRING",
        st.secrets.get("AZURE_STORAGE_CONNECTION_STRING", ""),
    )
    if not conn_str:
        return None
    try:
        return BlobServiceClient.from_connection_string(conn_str)
    except Exception:
        return None


def upload_to_blob(container_name: str, blob_name: str, content: str):
    """Upload a string to Azure Blob Storage. Fails silently if not configured."""
    client = get_blob_service_client()
    if client is None:
        return
    try:
        blob_client = client.get_blob_client(container=container_name, blob=blob_name)
        blob_client.upload_blob(content, overwrite=True)
    except Exception as e:
        # Log but don't crash the interview
        print(f"Blob upload error: {e}")


# Password screen for dashboard (note: only very basic authentication!)
# Based on https://docs.streamlit.io/knowledge-base/deploy/authentication-without-sso
def check_password():
    """Returns 'True' if the user has entered a correct password."""

    def login_form():
        """Form with widgets to collect user information"""
        with st.form("Credentials"):
            st.text_input("Username", key="username")
            st.text_input("Password", type="password", key="password")
            st.form_submit_button("Log in", on_click=password_entered)

    def password_entered():
        """Checks whether username and password entered by the user are correct."""
        if st.session_state.username in st.secrets.passwords and hmac.compare_digest(
            st.session_state.password,
            st.secrets.passwords[st.session_state.username],
        ):
            st.session_state.password_correct = True

        else:
            st.session_state.password_correct = False

        del st.session_state.password  # don't store password in session state

    # Return True, username if password was already entered correctly before
    if st.session_state.get("password_correct", False):
        return True, st.session_state.username

    # Otherwise show login screen
    login_form()
    if "password_correct" in st.session_state:
        st.error("User or password incorrect")
    return False, st.session_state.username


def check_if_interview_completed(directory, username):
    """Check if interview transcript/time file exists which signals that interview was completed."""

    # Test account has multiple interview attempts
    if username != "testaccount":

        # Check if file exists
        try:
            with open(os.path.join(directory, f"{username}.txt"), "r") as _:
                return True

        except FileNotFoundError:
            return False

    else:

        return False


def save_interview_data(
    username,
    transcripts_directory,
    times_directory,
    file_name_addition_transcript="",
    file_name_addition_time="",
    blob_container=None,
):
    """Write interview data (transcript and time) to disk and optionally to Azure Blob Storage."""

    # Build transcript content
    transcript_content = ""
    for message in st.session_state.messages:
        transcript_content += f"{message['role']}: {message['content']}\n"

    # Build time content
    duration = (time.time() - st.session_state.start_time) / 60
    time_content = (
        f"Start time (UTC): {time.strftime('%d/%m/%Y %H:%M:%S', time.localtime(st.session_state.start_time))}\n"
        f"Interview duration (minutes): {duration:.2f}"
    )

    # Save to local disk
    os.makedirs(transcripts_directory, exist_ok=True)
    os.makedirs(times_directory, exist_ok=True)

    transcript_filename = f"{username}{file_name_addition_transcript}.txt"
    time_filename = f"{username}{file_name_addition_time}.txt"

    with open(os.path.join(transcripts_directory, transcript_filename), "w") as t:
        t.write(transcript_content)

    with open(os.path.join(times_directory, time_filename), "w") as d:
        d.write(time_content)

    # Upload to Azure Blob Storage
    if blob_container:
        upload_to_blob(
            blob_container,
            f"transcripts/{transcript_filename}",
            transcript_content,
        )
        upload_to_blob(
            blob_container,
            f"times/{time_filename}",
            time_content,
        )
