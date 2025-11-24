import os
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "app.db")  # fallback for quick dev
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    CRIME_MODEL_PATH = os.getenv(
        "CRIME_MODEL_PATH",
        "OPear/videomae-large-finetuned-UCF-Crime"
    )

    