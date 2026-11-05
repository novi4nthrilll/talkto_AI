"""
Modul Suara (TTS) — ubah teks jadi audio, lalu putar atau simpan.
Mendukung edge-tts dan gTTS.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
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
    """Generate audio via edge-tts dengan pengaturan rate & pitch."""
    import edge_tts

    rate = getattr(config, "tts_rate", "+10%")
    pitch = getattr(config, "tts_pitch", "+0Hz")
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(output_path))
    log.info("edge-tts (%s, rate=%s) → %s", voice, rate, output_path)
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


# ── Engine: ElevenLabs (Paling Luwes & Mirip Manusia) ────────
async def _tts_elevenlabs(text: str, output_path: Path, voice: str) -> Path:
    """
    Generate audio via ElevenLabs API (paling luwes, ekspresif & human-like).
    Gunakan model eleven_multilingual_v2.
    """
    import os
    import httpx

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ELEVENLABS_API_KEY belum diisi di .env! "
            "Dapatkan key gratis di https://elevenlabs.io"
        )

    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "") or (
        voice if voice and not voice.startswith("id-ID") else "21m00Tcm4TlvDq8ikWAM"
    )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "style": 0.3,
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    log.info("elevenlabs (%s) → %s", voice_id, output_path)
    return output_path


# ── Engine: OpenAI TTS ──────────────────────────────────────
async def _tts_openai(text: str, output_path: Path, voice: str) -> Path:
    """Generate audio via OpenAI TTS API (tts-1)."""
    import os
    import httpx

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY belum diisi di .env")

    voice_name = (
        voice
        if voice in ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
        else "nova"
    )
    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "tts-1",
        "input": text,
        "voice": voice_name,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    log.info("openai-tts (%s) → %s", voice_name, output_path)
    return output_path


# ── Dispatcher ──────────────────────────────────────────────
_ENGINES = {
    "edge-tts": _tts_edge,
    "gtts": _tts_gtts,
    "elevenlabs": _tts_elevenlabs,
    "openai": _tts_openai,
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


def _play_and_cleanup_worker(cmd: list[str], path: Path, delete_after: bool) -> None:
    """Worker background untuk memutar audio lalu menghapus filenya jika diminta."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=(sys.platform == "win32"),
        )
        proc.wait()
    except Exception as exc:
        log.warning("Gagal memutar audio dengan %s: %s", cmd[0], exc)
    finally:
        if delete_after:
            try:
                # Beri sedikit jeda agar process benar-benar melepaskan file handle
                time.sleep(0.5)
                if path.exists():
                    path.unlink()
                    log.info("File audio dihapus permanen: %s", path)
            except Exception as exc:
                log.debug("Gagal menghapus file audio %s: %s", path, exc)


def play_audio(path: Path, delete_after: bool | None = None) -> None:
    """
    Putar file audio secara otomatis di background.
    Jika delete_after=True (default sesuai config), file dihapus permanen setelah selesai diputar.
    """
    if delete_after is None:
        delete_after = config.auto_delete_audio

    players: list[list[str]] = []

    if sys.platform == "linux":
        # Prioritaskan mpg123, mpv, ffplay, paplay, lalu xdg-open
        players = [
            ["mpg123", "-q", str(path)],
            ["mpv", "--no-video", str(path)],
            ["ffplay", "-nodisp", "-autoexit", str(path)],
            ["paplay", str(path)],
            ["xdg-open", str(path)],
        ]
    elif sys.platform == "darwin":
        players = [["afplay", str(path)], ["open", str(path)]]
    elif sys.platform == "win32":
        players = [["start", "", str(path)]]

    for cmd in players:
        binary = cmd[0]
        # Pastikan binary tersedia di sistem
        if sys.platform != "win32" and not shutil.which(binary):
            continue

        try:
            thread = threading.Thread(
                target=_play_and_cleanup_worker,
                args=(cmd, path, delete_after),
                daemon=True,
            )
            thread.start()
            return
        except Exception as exc:
            log.warning("Gagal memulai player %s: %s", binary, exc)
            continue

    log.info("Tidak ada audio player yang tersedia. File: %s", path)
    if delete_after and path.exists():
        try:
            path.unlink()
        except Exception:
            pass
