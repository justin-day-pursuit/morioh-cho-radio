# Morning briefing for Morioh Cho Radio.
#
# What this file does:
# Kai Harada checks unread Gmail, today's calendar, and recent Slack
# messages, then reads them back as a short morning briefing.
#
# How to run it (from this folder):
#   .venv/bin/python haradaKai.py
#
# What you can change without touching the rest of the file:
# - MODEL_ID, if OpenRouter retires the free model.
# - MAX_REPLY_TOKENS, if the briefing is getting cut off. 4096 is a long reply.
# - GOOGLE_SCOPES, only if Google asks for a different permission name.
# - LOGIN_BROWSER, if the sign-in window should open in a different browser.
# - MAX_EMAILS, if you want more or fewer unread messages in the briefing.
# - The question inside run(), if you want a different opening line.
#
# Before the first real briefing, open .env and replace SLACK_BOT_TOKEN
# with a real Slack token. The Google sign-in from the hello test only
# allowed name and email. The first run of this file opens the browser
# again so you can allow Gmail and Calendar.

import os
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from strands import Agent, tool
from strands.models.litellm import LiteLLMModel

# The address of OpenRouter. LiteLLM calls this api_base.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# The free model on OpenRouter. Change this line to try a different model.
MODEL_ID = "openrouter/openrouter/free"

# How long the briefing is allowed to be. A token is roughly one short word.
MAX_REPLY_TOKENS = 4096

# The sentence Kai is asked every morning.
BRIEFING_REQUEST = "What did I miss? Give me my morning briefing."

# Google's desktop login file, downloaded from Google Cloud.
CREDENTIALS_FILE = "credentials.json"

# Saved after a successful Google sign-in. Later runs reuse this file.
# It is listed in .gitignore, so it is not uploaded to GitHub.
TOKEN_FILE = "token.json"

# Read-only access to mail and calendar. Kai can look, not send or edit.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# "safari" is the browser name Python uses on this Mac.
# Change this word if a later run should use a different browser.
LOGIN_BROWSER = "safari"

# Stop after this many unread emails so a full inbox cannot overwhelm the briefing.
MAX_EMAILS = 25

# The stand-in values in .env until real keys are pasted in.
PLACEHOLDER_OPENROUTER_KEY = "sk-or-your-key-here"
PLACEHOLDER_SLACK_TOKEN = "xoxp-your-token-here"

# Kai must use the tool results, in this order, and keep these headings.
SYSTEM_PROMPT = """
You are Kai Harada, the morning host of Morioh Cho Radio.
Give the listener a briefing about what they missed.

Always call these tools, in this order, before you write the briefing:
1. check_gmail
2. check_calendar
3. check_slack

Use only what those tools return. If a tool reports an error or an empty
list, say that source had nothing to report. Do not invent emails, events,
or Slack messages.

Then write the briefing with these exact section headings, in this order:
URGENT
UPCOMING EVENTS
SLACK HIGHLIGHTS
OTHER EMAILS
SUGGESTED ACTIONS

Put time-sensitive mail and meetings that need a decision under URGENT.
Put the calendar under UPCOMING EVENTS.
Put the Slack messages under SLACK HIGHLIGHTS.
Put the remaining mail under OTHER EMAILS.
Close with a few concrete next steps under SUGGESTED ACTIONS.
""".strip()


def load_secret(name, placeholder):
    """Read one secret from the .env file in this folder.

    Returns the value, or an empty string when it is missing or still
    the example text. Callers decide whether that should stop the run.
    """
    load_dotenv()
    value = os.getenv(name, "").strip()
    if not value or value == placeholder:
        return ""
    return value


def get_google_credentials():
    """Sign in to Google and return the saved login.

    Reads token.json when this computer has already signed in with the
    Gmail and Calendar permissions. If that file is missing, expired, or
    was created for a smaller set of permissions, Safari opens so you can
    approve access. The new login is written back to token.json.
    """
    # Google sometimes adds an extra permission to the token. Accept it.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    creds = None
    if os.path.exists(TOKEN_FILE):
        # Load the file as it was saved. Passing scopes here would pretend
        # the old login already had Gmail and Calendar permission.
        creds = Credentials.from_authorized_user_file(TOKEN_FILE)

    has_mail_and_calendar = bool(creds) and creds.has_scopes(GOOGLE_SCOPES)
    if creds and creds.expired and creds.refresh_token and has_mail_and_calendar:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
        has_mail_and_calendar = creds.valid and creds.has_scopes(GOOGLE_SCOPES)

    if not creds or not creds.valid or not has_mail_and_calendar:
        if not os.path.exists(CREDENTIALS_FILE):
            print(
                "Put the Google credentials.json file in this folder, "
                "then run this file again."
            )
            sys.exit(1)
        print(
            "Safari is opening so you can allow Gmail and Calendar. "
            "Sign in with the Google account for this radio project.",
            flush=True,
        )
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE, GOOGLE_SCOPES
        )
        creds = flow.run_local_server(
            port=0, open_browser=True, browser=LOGIN_BROWSER
        )
        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
        print("Saved token.json in this folder.")

    return creds


def _header_value(message, header_name):
    """Pull one header, such as Subject, out of a Gmail message."""
    headers = message.get("payload", {}).get("headers", [])
    for header in headers:
        if header.get("name", "").lower() == header_name.lower():
            return header.get("value", "")
    return ""


@tool
def check_gmail(hours_back: int = 12):
    """Fetch unread Gmail from the last few hours.

    Returns the sender, subject, date, and a 200-character snippet for
    each unread email. hours_back is how far back to look. The default
    of 12 hours covers overnight mail.
    """
    try:
        creds = get_google_credentials()
        gmail = build("gmail", "v1", credentials=creds)
        # after: is a Gmail search clock, counted in seconds.
        cutoff = int(time.time()) - (hours_back * 60 * 60)
        response = (
            gmail.users()
            .messages()
            .list(
                userId="me",
                q=f"is:unread after:{cutoff}",
                maxResults=MAX_EMAILS,
            )
            .execute()
        )

        emails = []
        for item in response.get("messages", []):
            message = (
                gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            emails.append(
                {
                    "sender": _header_value(message, "From"),
                    "subject": _header_value(message, "Subject"),
                    "date": _header_value(message, "Date"),
                    "snippet": (message.get("snippet") or "")[:200],
                }
            )
        return {"hours_back": hours_back, "emails": emails}
    except Exception as error:
        return {"error": f"Gmail could not be checked: {error}"}


@tool
def check_calendar(hours_ahead: int = 24):
    """Fetch upcoming events from the main Google Calendar.

    Returns each event's title, start, end, location, and attendees.
    hours_ahead is how far forward to look. The default is 24 hours.
    """
    try:
        creds = get_google_credentials()
        calendar = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc)
        until = now + timedelta(hours=hours_ahead)
        response = (
            calendar.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=until.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = []
        for event in response.get("items", []):
            start = event.get("start", {})
            end = event.get("end", {})
            attendees = []
            for person in event.get("attendees", []):
                attendees.append(
                    person.get("displayName") or person.get("email") or "unknown"
                )
            events.append(
                {
                    "title": event.get("summary") or "(no title)",
                    "start": start.get("dateTime") or start.get("date") or "",
                    "end": end.get("dateTime") or end.get("date") or "",
                    "location": event.get("location") or "",
                    "attendees": attendees,
                }
            )
        return {"hours_ahead": hours_ahead, "events": events}
    except Exception as error:
        return {"error": f"Calendar could not be checked: {error}"}


@tool
def check_slack(hours_back: int = 12, max_channels: int = 5):
    """Fetch recent Slack messages from the busiest channels.

    Picks the most recently active channels, up to max_channels (default
    5). For each channel, returns the channel name and up to 5 messages
    from the last hours_back hours (default 12).
    """
    token = load_secret("SLACK_BOT_TOKEN", PLACEHOLDER_SLACK_TOKEN)
    if not token:
        return {
            "error": (
                "Open .env and replace SLACK_BOT_TOKEN with a real Slack "
                "token, then run this file again."
            )
        }

    try:
        slack = WebClient(token=token)
        listing = slack.conversations_list(
            types="public_channel,private_channel",
            exclude_archived=True,
            limit=200,
        )
        channels = listing.get("channels", [])
        # Slack's "updated" time is when the channel last changed.
        # The largest numbers are the channels people used most recently.
        channels.sort(key=lambda channel: float(channel.get("updated") or 0), reverse=True)

        cutoff = str(time.time() - (hours_back * 60 * 60))
        chosen = []
        for channel in channels[:max_channels]:
            history = slack.conversations_history(
                channel=channel["id"],
                oldest=cutoff,
                limit=5,
            )
            messages = []
            for message in history.get("messages", []):
                # Skip join and leave notices. They are not something you missed.
                if message.get("subtype"):
                    continue
                text = message.get("text") or ""
                if not text:
                    continue
                messages.append(
                    {
                        "user": message.get("user") or message.get("username") or "unknown",
                        "text": text,
                    }
                )
                if len(messages) == 5:
                    break
            chosen.append(
                {
                    "channel": channel.get("name") or channel.get("id"),
                    "messages": messages,
                }
            )
        return {"hours_back": hours_back, "channels": chosen}
    except SlackApiError as error:
        detail = error.response.get("error", str(error))
        return {"error": f"Slack could not be checked: {detail}"}
    except Exception as error:
        return {"error": f"Slack could not be checked: {error}"}


def run():
    """Build Kai and ask for the morning briefing.

    The briefing is printed in the terminal. The same text is returned
    so another program can use it later.
    """
    api_key = load_secret("OPENROUTER_API_KEY", PLACEHOLDER_OPENROUTER_KEY)
    if not api_key:
        print(
            "Open .env in this folder and replace OPENROUTER_API_KEY "
            "with your real OpenRouter key, then run this file again."
        )
        sys.exit(1)

    # LiteLLM is the piece that talks to OpenRouter.
    # api_key and api_base are handed straight to LiteLLM.
    # params holds settings for this reply, including the length cap.
    model = LiteLLMModel(
        client_args={
            "api_key": api_key,
            "api_base": OPENROUTER_BASE_URL,
        },
        model_id=MODEL_ID,
        params={"max_tokens": MAX_REPLY_TOKENS},
    )

    # These three tools are the only ones Kai is allowed to use.
    # callback_handler=None keeps the final briefing from printing twice.
    agent = Agent(
        model=model,
        tools=[check_gmail, check_calendar, check_slack],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )

    print("Checking email, calendar, and Slack. This can take a minute.", flush=True)
    result = agent(BRIEFING_REQUEST)
    print(result)
    return result


# Running this file directly starts the briefing.
# Importing the file from somewhere else does not.
if __name__ == "__main__":
    run()
