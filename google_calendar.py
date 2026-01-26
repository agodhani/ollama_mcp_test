# google_calendar_service.py
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
import os
import json

SCOPES = ["https://www.googleapis.com/auth/calendar"]  # full access to create/update events

def get_calendar_service():
    """Return an authorized Google Calendar service.

    Uses token.json and credentials.json located next to this module so the
    service works regardless of the current working directory. If an existing
    token exists but doesn't include the required scopes, it will be removed so
    the user is prompted to re-authorize with the correct scopes.
    """
    creds = None
    module_dir = os.path.dirname(__file__)
    token_path = os.path.join(module_dir, "token.json")
    creds_path = os.path.join(module_dir, "credentials.json")

    # Load credentials from module-local token if present. Inspect the saved
    # token JSON directly so we don't accidentally inject requested scopes
    # when parsing the file.
    if os.path.exists(token_path):
        try:
            with open(token_path, "r") as f:
                token_data = json.load(f)
        except Exception:
            token_data = {}

        # token may store scopes under 'scopes' (list) or 'scope' (space-delimited)
        token_scopes = set()
        if isinstance(token_data.get("scopes"), list):
            token_scopes = set(token_data.get("scopes", []))
        elif isinstance(token_data.get("scope"), str):
            token_scopes = set(token_data.get("scope", "").split())

        if not set(SCOPES).issubset(token_scopes):
            # remove token so user will re-authorize with required scopes
            try:
                os.remove(token_path)
            except OSError:
                pass
            creds = None
        else:
            creds = Credentials.from_authorized_user_file(token_path)

    # If credentials are missing or invalid, run the OAuth flow. If a refresh
    # attempt fails with an invalid_scope or similar, remove the token and
    # re-run the flow so the user can re-consent.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                try:
                    os.remove(token_path)
                except OSError:
                    pass
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=8000)
            # save the credentials next to this module
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    return service
