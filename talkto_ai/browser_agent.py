"""
Modul Browser Agent — observe → think → act loop dengan Playwright.
Termasuk deteksi captcha akurat dan mekanisme pause/resume.
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


# ── Konstanta & Pola Captcha ───────────────────────────────
_CAPTCHA_FRAMES = [
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='turnstile']",
    "iframe[src*='challenge']",
]

_CAPTCHA_SELECTORS = [
    "#challenge-running",
    "#cf-turnstile",
    ".cf-turnstile-wrapper",
    "#captcha",
    ".g-recaptcha",
    ".h-captcha",
    "#challenge-stage",
    "form#challenge-form",
]

_CAPTCHA_TEXT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"verify you are human", re.I),
    re.compile(r"i('?|’)m not a robot", re.I),
    re.compile(r"confirm you are human", re.I),
    re.compile(r"checking your browser before accessing", re.I),
    re.compile(r"enable javascript and cookies to continue", re.I),
    re.compile(r"attention required! \| cloudflare", re.I),
    re.compile(r"just a moment\.\.\.", re.I),
]

# Script JavaScript untuk menandai elemen interaktif langsung di DOM browser
# Menghindari ketidakcocokan indeks antara observe dan action
_JS_EXTRACT_AND_TAG = """
() => {
    const selector = 'a, button, input, textarea, select, [role=button], [role=link], [role=textbox], [contenteditable=true]';
    // Hapus tanda data-talkto-id lama jika ada
    document.querySelectorAll('[data-talkto-id]').forEach(el => el.removeAttribute('data-talkto-id'));

    const candidates = Array.from(document.querySelectorAll(selector));
    const items = [];
    let idCounter = 0;

    for (const el of candidates) {
        if (idCounter >= 25) break;

        // Abaikan elemen tersembunyi
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;

        el.setAttribute('data-talkto-id', String(idCounter));

        const tag = el.tagName.toLowerCase();
        const type = el.getAttribute('type') || '';
        const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
        const placeholder = el.getAttribute('placeholder') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';
        const href = el.getAttribute('href') || '';
        const val = el.value || '';

        const labelParts = [];
        if (text) labelParts.push(text);
        else if (placeholder) labelParts.push(`placeholder="${placeholder}"`);
        else if (ariaLabel) labelParts.push(`aria-label="${ariaLabel}"`);
        else if (val) labelParts.push(`val="${val.slice(0, 30)}"`);

        const label = labelParts.join(' ') || '(tanpa teks)';

        let desc = `[${idCounter}] <${tag}`;
        if (type) desc += ` type="${type}"`;
        desc += `> ${label}`;

        if (tag === 'input' || tag === 'textarea' || el.getAttribute('contenteditable') === 'true') {
            desc += ' [BISA DIKETIK]';
        } else if (tag === 'select') {
            desc += ' [DROPDOWN]';
        } else if (href) {
            desc += ` → ${href.slice(0, 60)}`;
        }

        items.push(desc);
        idCounter++;
    }
    return items.join('\\n');
}
"""


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
def _clean_html(html: str, max_chars: int = 2000) -> str:
    """Strip HTML jadi teks inti, batasi panjang untuk hemat token."""
    soup = BeautifulSoup(html, "lxml")

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


async def _detect_captcha_page(page: Page) -> bool:
    """Deteksi captcha lewat DOM dan teks halaman secara akurat."""
    try:
        # 1. Cek iframe captcha
        for frame_sel in _CAPTCHA_FRAMES:
            frames = await page.query_selector_all(frame_sel)
            if frames:
                return True

        # 2. Cek elemen id / class khas captcha
        for sel in _CAPTCHA_SELECTORS:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return True

        # 3. Cek judul halaman
        title = await page.title()
        if any(
            p.search(title)
            for p in [
                re.compile(r"just a moment", re.I),
                re.compile(r"attention required", re.I),
                re.compile(r"recaptcha", re.I),
                re.compile(r"cloudflare", re.I),
            ]
        ):
            return True

        # 4. Cek teks spesifik di body
        body_text = await page.evaluate(
            "() => document.body ? document.body.innerText.slice(0, 3000) : ''"
        )
        return any(pat.search(body_text) for pat in _CAPTCHA_TEXT_PATTERNS)
    except Exception as exc:
        log.debug("Cek captcha gagal: %s", exc)
        return False


def _trim_messages(
    messages: list[dict[str, Any]],
    *,
    keep_system: int = 1,
    keep_recent: int = 6,
) -> list[dict[str, Any]]:
    """
    Batasi panjang history messages supaya tidak melebihi token limit.
    Simpan system prompt + instruksi awal + beberapa langkah terakhir.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    if len(non_system) <= keep_recent:
        return messages

    trimmed = system_msgs[:keep_system]
    trimmed.append(non_system[0])
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
- Daftar elemen interaktif (dengan indeks [id])
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
- `click <indeks>` — klik elemen berdasarkan indeks [id].
- `type <indeks> <teks>` — ketik di elemen [BISA DIKETIK] berdasarkan indeks [id].
- `press_enter` — tekan Enter pada keyboard (misal setelah mengetik query di search bar).
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
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        # Coba ambil objek JSON pertama yang valid
        match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
        if match:
            try:
                return _json.loads(match.group())
            except _json.JSONDecodeError:
                pass
        return {"thought": text, "action": "done", "extract": ""}


# ── Browser Agent ───────────────────────────────────────────
class BrowserAgent:
    """Agent yang mengendalikan browser untuk mencari informasi."""

    def __init__(self, headless: bool | None = None) -> None:
        self.headless = headless if headless is not None else config.browser_headless
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.state = AgentState.IDLE
        self._captcha_event: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        """Buka browser."""
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
            )
        except Exception as exc:
            err_msg = str(exc)
            if "Executable doesn't exist" in err_msg or "playwright install" in err_msg:
                raise RuntimeError(
                    "Browser Chromium belum di-download oleh Playwright.\n"
                    "👉 Silakan jalankan perintah ini di terminal kamu:\n\n"
                    "    playwright install chromium\n"
                ) from None
            raise
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        log.info("Browser dimulai (headless=%s)", self.headless)

    async def stop(self) -> None:
        """Tutup browser."""
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        log.info("Browser ditutup")

    async def _observe(self) -> dict[str, str]:
        """Ambil kondisi halaman saat ini dan tandai elemen interaktif di DOM."""
        if self._page is None:
            raise RuntimeError("Browser belum dimulai.")

        url = self._page.url
        html = await self._page.content()
        page_text = _clean_html(html)

        # Tag elemen interaktif langsung di DOM browser & dapatkan deskripsinya
        try:
            interactive = await self._page.evaluate(_JS_EXTRACT_AND_TAG)
        except Exception as exc:
            log.warning("Gagal menandai elemen DOM: %s", exc)
            interactive = "(gagal membaca elemen interaktif)"

        return {
            "url": url,
            "page_text": page_text,
            "interactive": interactive or "(tidak ada elemen interaktif)",
        }

    async def _take_screenshot(self) -> str:
        """Ambil screenshot dan encode ke base64."""
        if self._page is None:
            raise RuntimeError("Browser belum dimulai.")
        raw = await self._page.screenshot(type="png")
        return encode_screenshot(raw)

    async def _execute_action(self, action: str) -> None:
        """Jalankan aksi dari agent menggunakan selector data-talkto-id yang terpasang di DOM."""
        if self._page is None:
            raise RuntimeError("Browser belum dimulai.")

        parts = action.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "goto":
            url = arg.strip()
            if not url.startswith("http"):
                url = "https://" + url
            log.info("→ goto %s", url)
            await self._page.goto(
                url, wait_until="domcontentloaded", timeout=30_000
            )

        elif cmd == "click":
            idx = int(arg)
            locator = self._page.locator(f'[data-talkto-id="{idx}"]')
            count = await locator.count()
            if count > 0:
                log.info("→ click [%d]", idx)
                try:
                    await locator.first.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                await locator.first.click(timeout=5000)
                try:
                    await self._page.wait_for_load_state(
                        "domcontentloaded", timeout=10_000
                    )
                except Exception:
                    await asyncio.sleep(1)
            else:
                log.warning("Elemen dengan id [%d] tidak ditemukan di halaman", idx)

        elif cmd == "type":
            type_parts = arg.split(maxsplit=1)
            idx = int(type_parts[0])
            text = type_parts[1] if len(type_parts) > 1 else ""
            locator = self._page.locator(f'[data-talkto-id="{idx}"]')
            count = await locator.count()
            if count > 0:
                log.info("→ type [%d] '%s'", idx, text[:40])
                try:
                    await locator.first.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                await locator.first.click(timeout=3000)
                await locator.first.fill(text)
            else:
                log.warning("Elemen dengan id [%d] tidak ditemukan untuk type", idx)

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
            pass

        else:
            log.warning("Aksi tidak dikenali: %s", action)

    async def _handle_captcha(self, on_captcha, timeout_seconds: float = 300.0) -> None:
        """Pause dan tunggu pengguna menyelesaikan captcha dengan batas waktu."""
        self.state = AgentState.PAUSED_CAPTCHA
        self._captcha_event.clear()

        if on_captcha:
            on_captcha(
                "⚠️  CAPTCHA terdeteksi! Selesaikan di browser, "
                "lalu tekan Enter di terminal (batas waktu 5 menit)."
            )

        log.info("Agent di-pause — menunggu captcha diselesaikan...")
        try:
            await asyncio.wait_for(self._captcha_event.wait(), timeout=timeout_seconds)
            self.state = AgentState.RUNNING
            log.info("Captcha diselesaikan — melanjutkan agent")
        except asyncio.TimeoutError:
            log.warning("Timeout menunggu penyelesaian captcha.")
            self.state = AgentState.ERROR
            raise RuntimeError("Waktu menunggu penyelesaian captcha habis (5 menit).")

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
        max_steps: int | None = None,
    ) -> AgentResult:
        """
        Jalankan agent loop observe → think → act.
        """
        steps_limit = max_steps or config.max_steps
        result = AgentResult(goal=goal)
        self.state = AgentState.RUNNING

        try:
            await self.start()
            if self._page is None:
                raise RuntimeError("Gagal menginisialisasi browser page.")

            await self._page.goto(
                start_url, wait_until="domcontentloaded", timeout=30_000
            )

            history_lines: list[str] = []
            collected_texts: list[str] = []

            for step_num in range(1, steps_limit + 1):
                # 1. Cek captcha sebelum observe
                if await _detect_captcha_page(self._page):
                    await self._handle_captcha(on_captcha)

                # 2. Observe (juga memberi tag data-talkto-id ke elemen DOM)
                obs = await self._observe()

                # Cek captcha lagi jika muncul setelah refresh
                if await _detect_captcha_page(self._page):
                    await self._handle_captcha(on_captcha)
                    obs = await self._observe()

                # 3. Think — kirim ke LLM (kompak, hemat token)
                history_text = (
                    "\n".join(history_lines[-4:]) if history_lines else "(langkah awal)"
                )
                obs_text = (
                    f"Tujuan: {goal}\n"
                    f"Langkah saat ini: {step_num}/{steps_limit}\n"
                    f"Riwayat langkah sebelumnya:\n{history_text}\n\n"
                    f"URL Halaman: {obs['url']}\n\n"
                    f"=== Teks Halaman ===\n{obs['page_text']}\n\n"
                    f"=== Elemen Interaktif ===\n{obs['interactive']}"
                )

                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": _AGENT_SYSTEM},
                ]

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

                history_lines.append(f"- Langkah {step_num}: {thought[:60]} → {action}")

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

                await asyncio.sleep(1)

            result.collected_text = "\n\n---\n\n".join(collected_texts)
            result.state = AgentState.DONE

        except Exception as exc:
            log.exception("Agent error")
            result.state = AgentState.ERROR
            result.error = str(exc)

        finally:
            await self.stop()

        return result
