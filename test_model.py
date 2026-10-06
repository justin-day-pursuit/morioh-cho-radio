# Hello test for the radio agent's language model.
#
# What this file does:
# It signs this computer in to Google (the first run opens a browser
# window and saves token.json), reads the OpenRouter key from the .env
# file in this folder, asks a language model to say hello and name itself
# in one sentence, and prints that sentence.
#
# How to run it (from this folder):
#   .venv/bin/python test_model.py
#
# What you can change without touching the rest of the file:
# - The model name (MODEL_ID) if OpenRouter retires the free model.
# - The reply length (MAX_REPLY_TOKENS). 256 is a short answer.
# - The question (QUESTION) if you want to ask something else.

import os
import sys

from dotenv import load_dotenv
from strands import Agent
from strands.models.litellm import LiteLLMModel

# The address of OpenRouter. LiteLLM calls this api_base.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# The free model on OpenRouter. Change this line to try a different model.
MODEL_ID = "openrouter/openrouter/free"

# How long the reply is allowed to be. A token is roughly one short word.
MAX_REPLY_TOKENS = 256

# The sentence we send to the model.
QUESTION = "Say hello and tell me what model you are in one sentence."

# The value sitting in .env until a real key is pasted in.
PLACEHOLDER_KEY = "sk-or-your-key-here"

# Google's desktop login file, downloaded from Google Cloud.
CREDENTIALS_FILE = "credentials.json"

# Saved after a successful Google sign-in. Later runs reuse this file
# instead of opening the browser again. It is listed in .gitignore.
TOKEN_FILE = "token.json"

# What we ask Google for. These three lines only identify the account
# (name and email). Add another line here if a later feature needs
# Calendar, Gmail, or Drive.
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def load_openrouter_key():
    """Read OPENROUTER_API_KEY from the .env file in this folder.

    Stops the script with a plain message if the key is missing or still
    the placeholder, so we never send a bad key to OpenRouter.
    """
    # Pull every name=value line in .env into the environment for this run.
    load_dotenv()

    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key or key == PLACEHOLDER_KEY:
        print(
            "Open .env in this folder and replace OPENROUTER_API_KEY "
            "with your real OpenRouter key, then run this file again."
        )
        sys.exit(1)
    return key


def sign_in_to_google():
    """Open Google's login window once, then save token.json.

    token.json is the saved sign-in for this computer. The first run
    opens a browser so you can approve the radio project. After that,
    this function reuses the file and stays quiet.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    # Google sometimes returns an extra permission on the token. This
    # tells the login library to accept that instead of stopping.
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print(
                    "Put the Google credentials.json file in this folder, "
                    "then run this file again."
                )
                sys.exit(1)
            print(
                "Safari is opening. Sign in with the Google "
                "account for this radio project.",
                flush=True,
            )
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, GOOGLE_SCOPES
            )
            # "safari" is the browser name Python uses on this Mac.
            # Change this word if a later run should use a different browser.
            creds = flow.run_local_server(port=0, open_browser=True, browser="safari")

        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
        print("Saved token.json in this folder.")
    else:
        print("Google is already signed in. Using the existing token.json.")


def main():
    """Sign in to Google, then ask the model one question and print its reply."""
    sign_in_to_google()
    api_key = load_openrouter_key()

    # LiteLLM is the piece that talks to OpenRouter.
    # api_key and api_base are handed straight to LiteLLM.
    # params holds settings for this one reply, including the length cap.
    model = LiteLLMModel(
        client_args={
            "api_key": api_key,
            "api_base": OPENROUTER_BASE_URL,
        },
        model_id=MODEL_ID,
        params={"max_tokens": MAX_REPLY_TOKENS},
    )

    # tools=[] means this agent cannot call any tools. It can only answer.
    # callback_handler=None stops the reply from printing twice.
    agent = Agent(model=model, tools=[], callback_handler=None)

    result = agent(QUESTION)
    print(result)


if __name__ == "__main__":
    main()
