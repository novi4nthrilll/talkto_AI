"""
AI Web Agent — Cari info di internet lewat browser, jawab dengan teks & suara.
"""

from .browser_agent import AgentResult, AgentState, BrowserAgent, StepResult
from .config import config
from .llm import chat
from .router import RouteDecision, answer_directly, route_user_input
from .summarizer import summarize
from .tts import clean_text_for_speech, text_to_speech

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "config",
    "chat",
    "route_user_input",
    "answer_directly",
    "RouteDecision",
    "BrowserAgent",
    "AgentState",
    "AgentResult",
    "StepResult",
    "summarize",
    "clean_text_for_speech",
    "text_to_speech",
]
