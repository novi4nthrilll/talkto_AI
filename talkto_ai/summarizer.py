"""
Modul Rangkuman — menyusun jawaban akhir dari data yang dikumpulkan agent.
"""

from __future__ import annotations

import logging

from .llm import chat

log = logging.getLogger(__name__)

_SUMMARIZE_SYSTEM = """\
Kamu adalah asisten yang merangkum informasi dari internet.

Aturan:
1. Jawab berdasarkan DATA yang diberikan, jangan mengarang.
2. Jika data tidak cukup, katakan dengan jujur.
3. Sebutkan sumber (URL) jika ada.
4. Jawab dalam bahasa Indonesia, singkat dan santai.
5. Kalimat pendek supaya enak didengar saat dijadikan suara.
6. Gunakan poin-poin untuk informasi yang banyak.
"""


async def summarize(
    goal: str,
    collected_text: str,
    steps_summary: str = "",
) -> str:
    """
    Rangkum informasi yang dikumpulkan agent menjadi jawaban final.

    Parameters
    ----------
    goal : pertanyaan / tujuan awal pengguna
    collected_text : teks yang dikumpulkan dari halaman web
    steps_summary : ringkasan langkah-langkah agent (opsional)

    Returns
    -------
    str — jawaban final
    """
    if not collected_text.strip():
        return (
            "Maaf, agent tidak berhasil mengumpulkan informasi yang cukup. "
            "Coba lagi dengan pertanyaan yang lebih spesifik."
        )

    user_content = (
        f"**Pertanyaan pengguna:** {goal}\n\n"
        f"**Data yang terkumpul dari browsing:**\n{collected_text}\n"
    )
    if steps_summary:
        user_content += f"\n**Langkah-langkah agent:**\n{steps_summary}\n"

    messages = [
        {"role": "system", "content": _SUMMARIZE_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    answer = await chat(messages, max_tokens=2048)
    log.info("Rangkuman selesai — %d karakter", len(answer))
    return answer

