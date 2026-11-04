"""
Modul Router — Menganalisis perintah pengguna sebelum membuka browser.

Aturan:
- Hanya buka Chromium untuk isu terkini/berita baru/data realtime atau jika pengguna meminta mencari di web.
- Pertanyaan teknis, mekanik, coding, sains, pengetahuan umum, dan obrolan dijawab LANGSUNG oleh AI.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .llm import chat

log = logging.getLogger(__name__)

_ROUTER_SYSTEM = """\
Kamu adalah pengklasifikasi niat pencarian web untuk AI Assistant.
Tugasmu: Tentukan apakah pertanyaan pengguna WAJIB dicari di internet lewat browser (Chromium), atau bisa LANGSUNG dijawab oleh kecerdasan AI.

PRINSIP UTAMA:
Default adalah need_browser = false! Kebanyakan hal (teknis, mekanik, coding, teori, edukasi, obrolan) bisa langsung dijawab oleh AI tanpa membuka browser.

need_browser = true HANYA JIKA:
1. Isu terkini, berita hangat, update kejadian baru, gosip/peristiwa viral (contoh: "isu pilpres terbaru", "berita banjir hari ini", "pidato prabowo semalam", "skor liga champions tadi malam").
2. Data dinamis / harga realtime yang berubah setiap waktu (contoh: "harga emas hari ini", "kurs dollar sekarang", "cuaca besok di surabaya").
3. Pengguna secara EKSPLISIT meminta browsing/mencari di web (contoh: "tolong carikan di google...", "browsing info tentang...", "cek website X").

need_browser = false (JANGAN BUKA BROWSER, AI BISA JAWAB LANGSUNG):
1. Teknis, mekanik, otomotif, sains (contoh: "cara kerja karburator", "kenapa rem mobil bunyi decit", "cara kerja mesin turbo", "beda oli 10w40 dan 5w30", "cara setting klep motor").
2. Coding, programming, IT, matematika, logika (contoh: "cara buat loop di python", "apa itu docker", "rumus pitagoras", "cara fix error index out of range").
3. Pengetahuan umum, konsep ilmiah, ensiklopedia, sejarah (contoh: "kenapa langit biru", "siapa penemu bola lampu", "sejarah perang dunia 1", "cara kerja fotosintesis").
4. Percakapan santai, sapaan, tips harian, resep masakan, humor (contoh: "halo bro", "tips tidur nyenyak", "resep nasi goreng spesial", "lagi bosan nih").

Jawab HANYA dengan format JSON valid (tanpa markdown fence):
{
  "need_browser": true | false,
  "search_query": "kata kunci pencarian google jika need_browser true (kosongkan jika false)"
}
"""

_DIRECT_ANSWER_SYSTEM = """\
Kamu adalah asisten AI yang cerdas, ramah, dan berpengetahuan luas.
Kamu diajak ngobrol santai oleh pengguna.

Panduan menjawab:
1. Jawab dalam bahasa Indonesia yang jelas, santai, dan bersahabat (seperti ngobrol dengan teman, boleh gunakan panggilan 'bro').
2. Jika ditanya hal teknis/mekanik/coding, jelaskan secara runtut, praktis, dan mudah dipahami.
3. Gunakan kalimat yang enak didengar jika dibacakan menjadi audio.
4. Hindari format markdown yang terlalu rumit (tabel panjang, simbol aneh) agar nyaman didengar.
"""


@dataclass
class RouteDecision:
    need_browser: bool
    search_query: str = ""


async def route_user_input(text: str) -> RouteDecision:
    """
    Analisis input pengguna: apakah butuh browser Chromium atau tidak.
    """
    # Fast path untuk sapaan pendek
    lower = text.lower().strip()
    if lower in ("halo", "hai", "halo bro", "hi", "tes", "test", "p", "pagi", "siang", "malam"):
        return RouteDecision(need_browser=False, search_query="")

    messages = [
        {"role": "system", "content": _ROUTER_SYSTEM},
        {"role": "user", "content": text},
    ]

    try:
        raw = await chat(messages, max_tokens=200, temperature=0.1)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            need_browser = bool(data.get("need_browser", False))
            search_query = data.get("search_query", "").strip() or text
            return RouteDecision(
                need_browser=need_browser,
                search_query=search_query,
            )
    except Exception as exc:
        log.warning("Router gagal parsing (%s), default langsung dijawab AI.", exc)

    return RouteDecision(need_browser=False, search_query="")


async def answer_directly(query: str) -> str:
    """
    Jawab langsung pertanyaan pengguna (teknis, mekanik, obrolan, pengetahuan umum)
    tanpa perlu membuka browser Chromium.
    """
    messages = [
        {"role": "system", "content": _DIRECT_ANSWER_SYSTEM},
        {"role": "user", "content": query},
    ]
    return await chat(messages, max_tokens=1500, temperature=0.5)
