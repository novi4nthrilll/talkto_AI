"""
Modul Suara (TTS) — ubah teks jadi audio, lalu putar atau simpan.
Mendukung edge-tts dan gTTS.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
from pathlib import Path

from .config import config

log = logging.getLogger(__name__)


# ── Pembersih teks ──────────────────────────────────────────
def clean_text_for_speech(text: str) -> str:
    """Bersihkan markdown, URL panjang, dan simbol aneh supaya TTS tidak baca karakter aneh."""
    # Hapus markdown headers
    text = re.sub(r"#{1,6}\s*", "", text)
    # Hapus bold/italic markers
    text = re.sub(r"\*{1,3}|_{1,3}", "", text)
    # Hapus markdown links → ambil teksnya saja
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Hapus URL standalone
    text = re.sub(r"https?://\S+", "", text)
    # Hapus backtick code
    text = re.sub(r"`[^`]*`", "", text)
    # Hapus simbol bullet
    text = re.sub(r"^[\-\*•]\s*", "", text, flags=re.MULTILINE)
    # Hapus garis horizontal
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    # Bersihkan whitespace berlebih
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()


def _truncate_for_speech(text: str, max_chars: int = 1500) -> str:
    """Potong teks panjang supaya audio tidak terlalu lama."""
    if len(text) <= max_chars:
        return text
    # Potong di batas kalimat terdekat
    truncated = text[:max_chars]
    last_dot = truncated.rfind(".")
    if last_dot > max_chars // 2:
        truncated = truncated[: last_dot + 1]
    return truncated + " ... dan seterusnya."


# ── Engine: edge-tts ────────────────────────────────────────
async def _tts_edge(text: str, output_path: Path, voice: str) -> Path:
    """Generate audio via edge-tts (async)."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))
    log.info("edge-tts → %s", output_path)
    return output_path


# ── Engine: gTTS ────────────────────────────────────────────
async def _tts_gtts(text: str, output_path: Path, _voice: str) -> Path:
    """Generate audio via gTTS — jalan di thread supaya tidak block event loop."""
    from gtts import gTTS

    def _generate():
        tts = gTTS(text=text, lang="id")
        tts.save(str(output_path))

    await asyncio.to_thread(_generate)
    log.info("gTTS → %s", output_path)
    return output_path


# ── Dispatcher ──────────────────────────────────────────────
_ENGINES = {
    "edge-tts": _tts_edge,
    "gtts": _tts_gtts,
}


async def text_to_speech(
    text: str,
    *,
    filename: str = "jawaban.mp3",
    engine: str | None = None,
    voice: str | None = None,
    max_chars: int = 1500,
) -> Path:
    """
    Ubah teks menjadi file audio.

    Parameters
    ----------
    text : teks yang mau dijadikan suara
    filename : nama file output
    engine : TTS engine (default dari config)
    voice : suara TTS (default dari config)
    max_chars : batas panjang teks untuk speech

    Returns
    -------
    Path — path ke file audio yang dihasilkan
    """
    engine = engine or config.tts_engine
    voice = voice or config.tts_voice

    # Bersihkan dan potong
    cleaned = clean_text_for_speech(text)
    cleaned = _truncate_for_speech(cleaned, max_chars)

    if not cleaned:
        cleaned = "Tidak ada informasi untuk dibacakan."

    # Siapkan output dir
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    # Pilih engine
    engine_fn = _ENGINES.get(engine)
    if engine_fn is None:
        log.warning("Engine '%s' tidak dikenali, fallback ke edge-tts", engine)
        engine_fn = _tts_edge

    await engine_fn(cleaned, output_path, voice)
    return output_path


def play_audio(path: Path) -> None:
    """Coba putar file audio. Kalau gagal, print path-nya saja."""
    players: list[list[str]] = []

    if sys.platform == "linux":
        # Coba player ringan dulu, baru fallback ke xdg-open
        players = [
            ["mpv", "--no-video", str(path)],
            ["ffplay", "-nodisp", "-autoexit", str(path)],
            ["aplay", str(path)],
            ["xdg-open", str(path)],
        ]
    elif sys.platform == "darwin":
        players = [["afplay", str(path)], ["open", str(path)]]
    elif sys.platform == "win32":
        players = [["start", "", str(path)]]

    for cmd in players:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=(sys.platform == "win32"),
            )
            return
        except FileNotFoundError:
            continue
        except Exception as exc:
            log.warning("Gagal memutar dengan %s: %s", cmd[0], exc)
            continue

    log.info("Tidak ada audio player yang tersedia. File: %s", path)
