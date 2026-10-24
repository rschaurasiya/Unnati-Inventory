import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings with environment variable support."""
    APP_NAME: str = "Shopkeeper-Customer Voice Billing & AI Inventory System"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./data/shopkeeper.db"

    # Store Profile Details
    SHOP_NAME: str = "Apna Kirana Store"
    SHOP_ADDRESS: str = "Main Market, Sector 4, New Delhi"
    SHOP_PHONE: str = "+91 98765 43210"

    # JWT & Auth Settings
    JWT_SECRET_KEY: str = "apna-kirana-super-secret-jwt-key-2026-prod-guard"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Base directory paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
    FRONTEND_DIR: Path = Path(__file__).resolve().parent.parent / "frontend"
    UPLOADS_DIR: Path = Path(__file__).resolve().parent.parent / "data" / "uploads"
    TTS_CACHE_DIR: Path = Path(__file__).resolve().parent.parent / ".tts_cache"

    # Voice & TTS Multi-Layer Configuration
    VOICE_PROVIDER: str = "elevenlabs"  # "elevenlabs", "edge-tts", or "browser"
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "JBFqnCBsd6RMkjVDRZzb"
    ELEVENLABS_MODEL_ID: str = "eleven_flash_v2_5"
    EDGE_TTS_VOICE_EN: str = "en-IN-PrabhatNeural"
    EDGE_TTS_VOICE_HI: str = "hi-IN-SwaraNeural"

    # Groq AI Assistant Configuration
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "qwen/qwen3.8-27b"

    # Firebase Client Configuration (Project: unnati-03)
    FIREBASE_API_KEY: str = "AIzaSyDy8nIk6HW-gR6F3eM8B6mxPlxEiSGFoxM"
    FIREBASE_AUTH_DOMAIN: str = "unnati-03.firebaseapp.com"
    FIREBASE_DATABASE_URL: str = "https://unnati-03-default-rtdb.firebaseio.com"
    FIREBASE_PROJECT_ID: str = "unnati-03"
    FIREBASE_STORAGE_BUCKET: str = "unnati-03.firebasestorage.app"
    FIREBASE_MESSAGING_SENDER_ID: str = "17363807307"
    FIREBASE_APP_ID: str = "1:17363807307:web:ea4c22b547038d808071ce"
    FIREBASE_MEASUREMENT_ID: str = "G-UNNATI03"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

# Ensure local data directory exists for SQLite storage and TTS audio cache
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
