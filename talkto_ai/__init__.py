"""
AI Web Agent — Cari info di internet lewat browser, jawab dengan teks & suara.
"""

from .browser_agent import AgentResult, AgentState, BrowserAgent, StepResult
from .config import config
from .llm import chat
from .summarizer import summarize
from .tts import clean_text_for_speech, text_to_speech

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "config",
    "chat",
    "BrowserAgent",
    "AgentState",
    "AgentResult",
    "StepResult",
    "summarize",
    "clean_text_for_speech",
    "text_to_speech",
]
