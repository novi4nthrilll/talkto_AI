"""
Modul Browser Agent — observe → think → act loop dengan Playwright.
Termasuk deteksi captcha dan mekanisme pause/resume.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import config
from .llm import build_user_message, chat, encode_screenshot

log = logging.getLogger(__name__)


# ── Konstanta ───────────────────────────────────────────────
_CAPTCHA_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"captcha", re.I),
    re.compile(r"verify you are human", re.I),
    re.compile(r"i('|')m not a robot", re.I),
    re.compile(r"are you a robot", re.I),
    re.compile(r"security check", re.I),
    re.compile(r"challenge-platform", re.I),
    re.compile(r"hcaptcha", re.I),
    re.compile(r"recaptcha", re.I),
    re.compile(r"cf-turnstile", re.I),
]

# Selector gabungan — satu daftar untuk klik DAN type, supaya indeks konsisten
_INTERACTIVE_SELECTOR = (
    "a, button, input, textarea, select, "
    "[role=button], [role=link], [role=textbox], "
    "[contenteditable=true], input[type=submit]"
)


class AgentState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED_CAPTCHA = auto()
    DONE = auto()
    ERROR = auto()


@dataclass
class StepResult:
    step: int
    observation: str
    thought: str
    action: str
    url: str


@dataclass
class AgentResult:
    """Hasil akhir dari satu sesi agent."""

    goal: str
    steps: list[StepResult] = field(default_factory=list)
    collected_text: str = ""
    state: AgentState = AgentState.IDLE
    error: str | None = None


# ── Helper ──────────────────────────────────────────────────
def _clean_html(html: str, max_chars: int = 6000) -> str:
    """Strip HTML jadi teks inti, batasi panjang untuk hemat token."""
    soup = BeautifulSoup(html, "lxml")

    # Buang elemen yang tidak berguna
    for tag in soup(
        ["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]
    ):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cleaned = "\n".join(lines)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n... (dipotong)"
    return cleaned


def _detect_captcha(page_text: str, page_url: str) -> bool:
    """Cek apakah halaman mengandung indikasi captcha."""
    combined = page_text + " " + page_url
    return any(pat.search(combined) for pat in _CAPTCHA_PATTERNS)


def _extract_interactive_elements(html: str, max_items: int = 50) -> str:
    """
    Ambil SEMUA elemen interaktif (link, button, input, textarea, dll)
    dengan satu selector dan satu set indeks — supaya konsisten
    antara observe dan act.
    """
    soup = BeautifulSoup(html, "lxml")
    items: list[str] = []

    for i, el in enumerate(soup.select(_INTERACTIVE_SELECTOR)):
        if i >= max_items:
            break

        tag = el.name
        el_type = el.get("type", "")
        text = el.get_text(strip=True)[:80] or ""
        placeholder = el.get("placeholder", "")
        href = el.get("href", "")
        name = el.get("name", "")
        aria_label = el.get("aria-label", "")
        value = el.get("value", "")

        # Bangun label yang informatif
        label_parts: list[str] = []
        if text:
            label_parts.append(text)
        elif placeholder:
            label_parts.append(f'placeholder="{placeholder}"')
        elif aria_label:
            label_parts.append(f'aria-label="{aria_label}"')
        elif value:
            label_parts.append(f'value="{value}"')
        elif name:
            label_parts.append(f'name="{name}"')
        else:
            label_parts.append("(kosong)")

        label = " ".join(label_parts)

        # Tentukan tipe elemen
        if tag in ("input", "textarea") or el.get("contenteditable") == "true":
            kind = f"<{tag}" + (f' type="{el_type}"' if el_type else "") + ">"
            items.append(f"[{i}] {kind} {label} [BISA DIKETIK]")
        elif tag == "select":
            items.append(f"[{i}] <select> {label} [DROPDOWN]")
        elif href:
            items.append(f"[{i}] <{tag}> {label} → {href}")
        else:
            items.append(f"[{i}] <{tag}> {label}")

    return "\n".join(items) if items else "(tidak ada elemen interaktif)"


def _trim_messages(
    messages: list[dict[str, Any]],
    *,
    keep_system: int = 1,
    keep_recent: int = 6,
) -> list[dict[str, Any]]:
    """
    Batasi panjang history messages supaya tidak melebihi token limit.
    Simpan system prompt + beberapa langkah terakhir.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    if len(non_system) <= keep_recent:
        return messages

    # Ambil pesan pertama (tujuan awal) + pesan terbaru
    trimmed = system_msgs[:keep_system]
    trimmed.append(non_system[0])  # Tujuan awal
    trimmed.append(
        {
            "role": "user",
            "content": f"[... {len(non_system) - keep_recent - 1} langkah sebelumnya diringkas ...]",
        }
    )
    trimmed.extend(non_system[-keep_recent:])
    return trimmed


# ── System prompt untuk agent ───────────────────────────────
_AGENT_SYSTEM = """\
Kamu adalah browser agent. Tugasmu: navigasi web untuk mencapai tujuan user.

Di setiap langkah kamu akan diberi:
- URL halaman sekarang
- Teks inti halaman
- Daftar elemen interaktif (dengan indeks)
  - Elemen bertanda [BISA DIKETIK] bisa diisi teks pakai `type`
  - Elemen lain bisa diklik pakai `click`

Jawab **hanya** dengan satu blok JSON (tanpa markdown fence):
{
  "thought": "penjelasan singkat",
  "action": "salah satu dari: goto <url> | click <indeks> | type <indeks> <teks> | press_enter | scroll down | scroll up | extract | done",
  "extract": "teks penting yang kamu temukan (kosongkan jika belum ada)"
}

Aturan:
- `goto <url>` — buka halaman baru.
- `click <indeks>` — klik elemen berdasarkan indeks.
- `type <indeks> <teks>` — ketik di elemen [BISA DIKETIK] berdasarkan indeks.
- `press_enter` — tekan Enter (misal setelah mengetik query di search box).
- `scroll down` / `scroll up` — scroll halaman.
- `extract` — ambil informasi penting dari halaman saat ini.
- `done` — tujuan tercapai atau info sudah cukup.
- Selalu isi field `extract` jika menemukan informasi relevan.
- Jangan pernah coba solve captcha sendiri.
- Indeks elemen HARUS sesuai dengan daftar yang diberikan.
"""


def _parse_agent_response(text: str) -> dict[str, str]:
    """Parse JSON dari respons agent, toleran terhadap markdown fences."""
    text = text.strip()
    # Hapus markdown code fence jika ada
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        # Coba cari JSON di dalam teks
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return _json.loads(match.group())
            except _json.JSONDecodeError:
                pass
        return {"thought": text, "action": "done", "extract": ""}


# ── Browser Agent ───────────────────────────────────────────
class BrowserAgent:
    """Agent yang mengendalikan browser untuk mencari informasi."""

    def __init__(self) -> None:
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.state = AgentState.IDLE
        self._captcha_event: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        """Buka browser."""
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=config.browser_headless,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        log.info("Browser dimulai (headless=%s)", config.browser_headless)

    async def stop(self) -> None:
        """Tutup browser."""
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        log.info("Browser ditutup")

    async def _observe(self) -> dict[str, str]:
        """Ambil kondisi halaman saat ini."""
        assert self._page is not None
        url = self._page.url
        html = await self._page.content()
        page_text = _clean_html(html)
        interactive = _extract_interactive_elements(html)
        return {
            "url": url,
            "page_text": page_text,
            "interactive": interactive,
        }

    async def _take_screenshot(self) -> str:
        """Ambil screenshot dan encode ke base64."""
        assert self._page is not None
        raw = await self._page.screenshot(type="png")
        return encode_screenshot(raw)

    async def _execute_action(self, action: str) -> None:
        """Jalankan aksi dari agent."""
        assert self._page is not None
        parts = action.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "goto":
            url = arg.strip()
            if not url.startswith("http"):
                url = "https://" + url
            log.info("→ goto %s", url)
            try:
                await self._page.goto(
                    url, wait_until="domcontentloaded", timeout=30_000
                )
            except Exception as exc:
                log.warning("Gagal goto %s: %s", url, exc)
                raise

        elif cmd == "click":
            idx = int(arg)
            elements = await self._page.query_selector_all(_INTERACTIVE_SELECTOR)
            if 0 <= idx < len(elements):
                log.info("→ click [%d]", idx)
                try:
                    await elements[idx].scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass  # Kalau gagal scroll, tetap coba klik
                await elements[idx].click(timeout=5000)
                # Tunggu navigasi atau perubahan halaman
                try:
                    await self._page.wait_for_load_state(
                        "domcontentloaded", timeout=10_000
                    )
                except Exception:
                    await asyncio.sleep(1)
            else:
                log.warning(
                    "Indeks klik %d di luar jangkauan (%d elemen)", idx, len(elements)
                )

        elif cmd == "type":
            # format: type <idx> <teks>
            type_parts = arg.split(maxsplit=1)
            idx = int(type_parts[0])
            text = type_parts[1] if len(type_parts) > 1 else ""
            # Pakai selector yang SAMA dengan observe
            elements = await self._page.query_selector_all(_INTERACTIVE_SELECTOR)
            if 0 <= idx < len(elements):
                log.info("→ type [%d] '%s'", idx, text[:40])
                try:
                    await elements[idx].scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                await elements[idx].click(timeout=3000)
                await elements[idx].fill(text)
            else:
                log.warning("Indeks type %d di luar jangkauan (%d elemen)", idx, len(elements))

        elif cmd == "press_enter":
            log.info("→ press Enter")
            await self._page.keyboard.press("Enter")
            try:
                await self._page.wait_for_load_state(
                    "domcontentloaded", timeout=15_000
                )
            except Exception:
                await asyncio.sleep(1.5)

        elif cmd == "scroll":
            direction = arg.lower()
            delta = 600 if direction == "down" else -600
            log.info("→ scroll %s", direction)
            await self._page.mouse.wheel(0, delta)
            await asyncio.sleep(0.5)

        elif cmd in ("extract", "done"):
            pass  # Tidak ada aksi browser

        else:
            log.warning("Aksi tidak dikenali: %s", action)

    async def _handle_captcha(self, on_captcha) -> None:
        """Pause dan tunggu pengguna menyelesaikan captcha."""
        self.state = AgentState.PAUSED_CAPTCHA
        self._captcha_event.clear()

        if on_captcha:
            on_captcha(
                "⚠️  CAPTCHA terdeteksi! Selesaikan di browser, "
                "lalu tekan Enter di terminal."
            )

        log.info("Agent di-pause — menunggu captcha diselesaikan...")
        await self._captcha_event.wait()
        self.state = AgentState.RUNNING
        log.info("Captcha diselesaikan — melanjutkan agent")

    def resume_after_captcha(self) -> None:
        """Dipanggil setelah pengguna menyelesaikan captcha."""
        self._captcha_event.set()

    async def run(
        self,
        goal: str,
        *,
        start_url: str = "https://www.google.com",
        on_step=None,
        on_captcha=None,
        use_vision: bool = False,
    ) -> AgentResult:
        """
        Jalankan agent loop observe → think → act.

        Parameters
        ----------
        goal : tujuan pencarian
        start_url : URL awal
        on_step : callback(StepResult) tiap langkah
        on_captcha : callback(str) saat captcha terdeteksi
        use_vision : pakai screenshot (butuh model vision)
        """
        result = AgentResult(goal=goal)
        self.state = AgentState.RUNNING

        try:
            await self.start()
            assert self._page is not None
            await self._page.goto(
                start_url, wait_until="domcontentloaded", timeout=30_000
            )

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": _AGENT_SYSTEM},
                {
                    "role": "user",
                    "content": f"Tujuan: {goal}\n\nMulai dari: {start_url}",
                },
            ]

            collected_texts: list[str] = []

            for step_num in range(1, config.max_steps + 1):
                # 1. Observe
                obs = await self._observe()

                # 2. Cek captcha
                if _detect_captcha(obs["page_text"], obs["url"]):
                    await self._handle_captcha(on_captcha)
                    obs = await self._observe()  # Refresh setelah captcha

                # 3. Think — kirim ke LLM
                obs_text = (
                    f"Langkah {step_num}/{config.max_steps}\n"
                    f"URL: {obs['url']}\n\n"
                    f"=== Teks halaman ===\n{obs['page_text']}\n\n"
                    f"=== Elemen interaktif ===\n{obs['interactive']}"
                )

                # Trim message history supaya tidak melebihi token limit
                messages = _trim_messages(messages)

                if use_vision:
                    screenshot_b64 = await self._take_screenshot()
                    messages.append(build_user_message(obs_text, screenshot_b64))
                else:
                    messages.append({"role": "user", "content": obs_text})

                response = await chat(messages, vision=use_vision)
                parsed = _parse_agent_response(response)

                thought = parsed.get("thought", "")
                action = parsed.get("action", "done")
                extract = parsed.get("extract", "")

                messages.append({"role": "assistant", "content": response})

                step_res = StepResult(
                    step=step_num,
                    observation=obs_text[:200] + "...",
                    thought=thought,
                    action=action,
                    url=obs["url"],
                )
                result.steps.append(step_res)

                if on_step:
                    on_step(step_res)

                log.info(
                    "[Langkah %d] thought=%s | action=%s",
                    step_num,
                    thought[:60],
                    action,
                )

                # Kumpulkan teks yang di-extract
                if extract:
                    collected_texts.append(extract)

                # 4. Act
                if action.strip().lower() == "done":
                    log.info("Agent selesai di langkah %d", step_num)
                    break

                try:
                    await self._execute_action(action)
                except Exception as exc:
                    log.warning("Gagal eksekusi aksi '%s': %s", action, exc)
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Aksi gagal: {exc}. Coba langkah lain.",
                        }
                    )

                await asyncio.sleep(1)  # Jeda antar langkah

            result.collected_text = "\n\n---\n\n".join(collected_texts)
            result.state = AgentState.DONE

        except Exception as exc:
            log.exception("Agent error")
            result.state = AgentState.ERROR
            result.error = str(exc)

        finally:
            await self.stop()

        return result
