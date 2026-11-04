"""
Modul LLM — client OpenAI-compatible dengan fallback antar provider.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from .config import LLMProvider, config

log = logging.getLogger(__name__)

# Timeout per request (detik)
_TIMEOUT = 60.0

# Shared client — terikat ke event loop yang aktif
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


async def _get_client() -> httpx.AsyncClient:
    """Ambil atau buat shared async HTTP client yang terikat ke running event loop."""
    global _client, _client_loop
    import asyncio
    current_loop = asyncio.get_running_loop()
    if _client is None or _client.is_closed or _client_loop != current_loop:
        if _client is not None and not _client.is_closed:
            try:
                await _client.aclose()
            except Exception:
                pass
        _client = httpx.AsyncClient(timeout=_TIMEOUT)
        _client_loop = current_loop
    return _client


async def close_client() -> None:
    """Tutup shared client. Panggil saat shutdown."""
    global _client, _client_loop
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        _client_loop = None


class LLMError(Exception):
    """Gagal memanggil semua provider."""


async def _call_provider(
    provider: LLMProvider,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> str:
    """Kirim chat completion ke satu provider. Raise pada error."""
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": provider.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    url = f"{provider.base_url}/chat/completions"

    client = await _get_client()
    resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    text: str = data["choices"][0]["message"]["content"]
    log.info("Provider %s → %d karakter", provider.name, len(text))
    return text


async def chat(
    messages: list[dict[str, Any]],
    *,
    vision: bool = False,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> str:
    """
    Kirim pesan ke LLM dengan fallback otomatis.

    Parameters
    ----------
    messages : list of message dicts (OpenAI format)
    vision : jika True, hanya pakai provider yang support vision
    temperature : kreativitas jawaban
    max_tokens : panjang jawaban maks

    Returns
    -------
    str — teks jawaban dari LLM
    """
    providers = config.available_providers(vision=vision)
    if not providers:
        raise LLMError(
            "Tidak ada provider LLM yang tersedia. "
            "Pastikan minimal satu API key diisi di .env"
        )

    errors: list[str] = []
    for prov in providers:
        try:
            return await _call_provider(
                prov, messages, temperature=temperature, max_tokens=max_tokens
            )
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()[:200]
            msg = f"{prov.name}: HTTP {exc.response.status_code} ({detail})"
            log.warning("Gagal: %s", msg)
            errors.append(msg)
            # Retry sekali untuk error 429 (rate limit) dan 5xx
            if exc.response.status_code in (429, 500, 502, 503):
                import asyncio

                wait = 3.0 if exc.response.status_code == 429 else 1.0
                log.info("Retry %s setelah %.1f detik...", prov.name, wait)
                await asyncio.sleep(wait)
                try:
                    return await _call_provider(
                        prov,
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as retry_exc:
                    msg2 = f"{prov.name} (retry): {retry_exc}"
                    log.warning("Retry gagal: %s", msg2)
                    errors.append(msg2)
        except Exception as exc:
            msg = f"{prov.name}: {exc}"
            log.warning("Gagal: %s", msg)
            errors.append(msg)

    raise LLMError(
        "Semua provider gagal:\n" + "\n".join(f"  - {e}" for e in errors)
    )


def build_user_message(text: str, image_b64: str | None = None) -> dict:
    """
    Buat message user. Kalau ada screenshot, sertakan sebagai image_url.
    """
    if image_b64 is None:
        return {"role": "user", "content": text}

    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                },
            },
        ],
    }


def encode_screenshot(raw_bytes: bytes) -> str:
    """Encode screenshot ke base64 string."""
    return base64.b64encode(raw_bytes).decode()
