import os

from dotenv import load_dotenv


def load_environment():
    stage = os.getenv("STAGE", "development").strip().lower()
    if stage == "development":
        load_dotenv()
