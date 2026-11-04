"""
Konfigurasi terpusat — memuat .env dan menyediakan setting default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Muat .env dari root project
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


# ── Provider LLM ────────────────────────────────────────────
@dataclass
class LLMProvider:
    """Satu provider LLM dengan endpoint OpenAI-compatible."""

    name: str
    base_url: str
    api_key: str
    model: str
    supports_vision: bool = False

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)


def _build_providers() -> list[LLMProvider]:
    """Bangun daftar provider dari environment variables."""
    providers: list[LLMProvider] = []

    # --- Google Gemini (via OpenAI compat endpoint) ---
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        providers.append(
            LLMProvider(
                name="gemini",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                api_key=gemini_key,
                model="gemini-2.0-flash",
                supports_vision=True,
            )
        )

    # --- Groq ---
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        providers.append(
            LLMProvider(
                name="groq",
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
                model="llama-3.3-70b-versatile",
                supports_vision=False,
            )
        )

    # --- OpenRouter (model gratis) ---
    or_key = os.getenv("OPENROUTER_API_KEY", "")
    if or_key:
        providers.append(
            LLMProvider(
                name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key=or_key,
                model="google/gemini-2.0-flash-exp:free",
                supports_vision=True,
            )
        )

    return providers


# ── Setting utama ───────────────────────────────────────────
@dataclass
class Config:
    """Setting aplikasi — dibaca sekali saat start."""

    providers: list[LLMProvider] = field(default_factory=_build_providers)

    # Browser
    browser_headless: bool = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
    max_steps: int = int(os.getenv("MAX_STEPS", "15"))

    # TTS
    tts_engine: str = os.getenv("TTS_ENGINE", "edge-tts")
    tts_voice: str = os.getenv("TTS_VOICE", "id-ID-ArdiNeural")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Output
    output_dir: Path = Path(__file__).resolve().parent.parent / "output"

    def available_providers(self, vision: bool = False) -> list[LLMProvider]:
        """Provider yang punya API key (dan opsional support vision)."""
        return [
            p
            for p in self.providers
            if p.is_available and (not vision or p.supports_vision)
        ]


config = Config()

