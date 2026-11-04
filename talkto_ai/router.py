"""
Modul Router — Menganalisis perintah pengguna sebelum membuka browser.
Membedakan antara percakapan santai (dijawab langsung) dan permintaan pencarian internet.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .llm import chat

log = logging.getLogger(__name__)

_ROUTER_SYSTEM = """\
Kamu adalah AI Web Agent yang ramah dan cerdas.
Tugasmu: analisis pesan pengguna dan putuskan apakah perlu membuka browser untuk mencari informasi di internet, atau bisa dijawab langsung.

Aturan:
1. need_browser = false jika:
   - Sapaan / basa-basi (contoh: "halo", "pagi", "hai bro")
   - Percakapan umum / terima kasih / humor
   - Pertanyaan yang tidak butuh data realtime/spesifik web
   - Pertanyaan tentang siapa dirimu atau kemampuanmu
2. need_browser = true jika:
   - Pengguna meminta mencari sesuatu (contoh: "cari info...", "browsing...", "cek...")
   - Informasi terkini / berita baru (contoh: "pidato terbaru", "skor bola tadi malam", "cuaca hari ini")
   - Harga terkini, jadwal, review produk, artikel spesifik
   - Data faktual yang butuh verifikasi sumber web

Jawab HANYA dengan format JSON valid (tanpa markdown code fence):
{
  "need_browser": true | false,
  "search_query": "kata kunci pencarian ringkas jika need_browser true (kosongkan jika false)",
  "direct_reply": "jawaban ramah dalam bahasa Indonesia santai jika need_browser false (kosongkan jika true)"
}
"""


@dataclass
class RouteDecision:
    need_browser: bool
    search_query: str = ""
    direct_reply: str = ""


async def route_user_input(text: str) -> RouteDecision:
    """
    Analisis input pengguna: langsung jawab atau butuh browser.
    """
    messages = [
        {"role": "system", "content": _ROUTER_SYSTEM},
        {"role": "user", "content": text},
    ]

    try:
        raw = await chat(messages, max_tokens=300, temperature=0.2)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            need_browser = bool(data.get("need_browser", False))
            search_query = data.get("search_query", "").strip() or text
            direct_reply = data.get("direct_reply", "").strip()
            return RouteDecision(
                need_browser=need_browser,
                search_query=search_query,
                direct_reply=direct_reply,
            )
    except Exception as exc:
        log.warning("Router gagal parsing (%s), fallback ke browsing.", exc)

    # Fallback aman jika LLM gagal format JSON:
    # Jika sangat pendek / sapaan, anggap percakapan
    lower = text.lower().strip()
    if lower in ("halo", "hai", "halo bro", "hi", "tes", "test", "p"):
        return RouteDecision(
            need_browser=False,
            direct_reply="Halo bro! Ada yang bisa gw bantu cari di internet atau mau ngobrol apa nih?",
        )

    return RouteDecision(need_browser=True, search_query=text)

