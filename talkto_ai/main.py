"""
Main — entry point AI Web Agent.

Alur: perintah pengguna → browser agent → rangkuman → teks + suara.
Mendukung eksekusi langsung via argument atau mode interaktif.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from .browser_agent import AgentState, BrowserAgent, StepResult
from .config import config
from .llm import close_client
from .router import route_user_input
from .summarizer import summarize
from .tts import play_audio, text_to_speech

console = Console()


def _setup_logging() -> None:
    logging.basicConfig(
        level=config.log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


def _print_banner() -> None:
    banner = Text()
    banner.append("🤖 AI Web Agent", style="bold cyan")
    banner.append(
        "\n   Cari info di internet, jawab dengan teks & suara\n", style="dim"
    )
    console.print(Panel(banner, border_style="cyan"))


def _on_step(step: StepResult) -> None:
    """Callback setiap langkah agent — tampilkan progress."""
    console.print(
        f"  [bold yellow]Langkah {step.step}[/] "
        f"[dim]{step.url[:60]}[/]\n"
        f"  💭 {step.thought[:80]}\n"
        f"  ▶  {step.action}",
    )


def _on_captcha(message: str) -> None:
    """Callback saat captcha terdeteksi."""
    console.print(f"\n[bold red]{message}[/bold red]\n")


async def _wait_for_captcha_input(agent: BrowserAgent) -> None:
    """
    Tunggu input Enter dari user di thread terpisah saat captcha muncul.
    """
    await asyncio.to_thread(input)
    agent.resume_after_captcha()


async def _run_session(
    query: str,
    *,
    with_audio: bool = True,
    headless: bool | None = None,
    max_steps: int | None = None,
) -> None:
    """Jalankan satu sesi: analisis intensi dulu, baru buka browser jika butuh info web."""
    console.print(f"\n[bold green]💬 Input:[/] {query}")

    # 1. Analisis intensi pesan pengguna
    with console.status("[bold cyan]Memahami maksud kamu...[/]"):
        try:
            decision = await route_user_input(query)
        except Exception as exc:
            log.warning("Gagal routing intent: %s", exc)
            decision = None

    # Jika percakapan santai / pertanyaan umum -> Langsung jawab tanpa browser
    if decision and not decision.need_browser and decision.direct_reply:
        answer = decision.direct_reply
        console.print(Panel(answer, title="💬 Jawaban", border_style="cyan"))

        if with_audio:
            console.print("[bold cyan]🔊 Membuat audio...[/]")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                audio_path = await text_to_speech(
                    answer, filename=f"jawaban_{timestamp}.mp3"
                )
                console.print(f"[green]✅ Audio disimpan:[/] {audio_path}")
                play_audio(audio_path)
            except Exception as exc:
                console.print(f"[yellow]⚠️  Gagal buat audio: {exc}[/]")

        console.print()
        return

    # 2. Butuh pencarian di internet -> Buka browser agent
    target_query = (decision.search_query if decision and decision.search_query else query)
    console.print(f"[bold yellow]🌐 Butuh info web, membuka browser untuk:[/] {target_query}\n")

    agent = BrowserAgent(headless=headless)

    captcha_task: asyncio.Task | None = None

    def _captcha_handler(message: str) -> None:
        nonlocal captcha_task
        _on_captcha(message)
        captcha_task = asyncio.create_task(_wait_for_captcha_input(agent))

    use_vision = bool(config.available_providers(vision=True))
    result = await agent.run(
        goal=target_query,
        on_step=_on_step,
        on_captcha=_captcha_handler,
        use_vision=use_vision,
        max_steps=max_steps,
    )

    if captcha_task and not captcha_task.done():
        captcha_task.cancel()

    if result.state == AgentState.ERROR:
        console.print(f"\n[bold red]❌ Error:[/] {result.error}")
        return

    steps_summary = "\n".join(
        f"- Langkah {s.step}: {s.thought[:60]} → {s.action}" for s in result.steps
    )

    console.print("\n[bold cyan]📝 Merangkum jawaban...[/]")
    answer = await summarize(query, result.collected_text, steps_summary)

    console.print(Panel(answer, title="💬 Jawaban", border_style="green"))

    if with_audio:
        console.print("[bold cyan]🔊 Membuat audio...[/]")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            audio_path = await text_to_speech(
                answer, filename=f"jawaban_{timestamp}.mp3"
            )
            console.print(f"[green]✅ Audio disimpan:[/] {audio_path}")
            play_audio(audio_path)
        except Exception as exc:
            console.print(f"[yellow]⚠️  Gagal buat audio: {exc}[/]")

    console.print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="talkto",
        description="AI Web Agent — Cari info di internet lewat browser, jawab teks & suara.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Pertanyaan / tugas untuk dicari langsung (tanpa prompt interaktif)",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Jangan buat output audio (hanya teks)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Jalankan browser tanpa jendela (headless)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Batas maksimal langkah browsing agent (override config)",
    )
    return parser.parse_args()


async def _interactive_loop(
    with_audio: bool = True,
    headless: bool | None = None,
    max_steps: int | None = None,
) -> None:
    """Loop prompt interaktif di dalam satu event loop."""
    while True:
        try:
            query = await asyncio.to_thread(Prompt.ask, "[bold cyan]Tanya[/]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye! 👋[/]")
            break

        query = query.strip()
        if not query:
            continue
        if query.lower() in ("exit", "quit", "keluar"):
            console.print("[dim]Bye! 👋[/]")
            break

        await _run_session(
            query,
            with_audio=with_audio,
            headless=headless,
            max_steps=max_steps,
        )


def main() -> None:
    """Entry point CLI."""
    args = parse_args()
    _setup_logging()
    _print_banner()

    providers = config.available_providers()
    if not providers:
        console.print(
            "[bold red]❌ Tidak ada API key yang diset![/]\n"
            "   Salin .env.example → .env lalu isi minimal satu API key.\n"
        )
        sys.exit(1)

    console.print(
        f"[dim]Provider aktif: " f"{', '.join(p.name for p in providers)}[/]\n"
    )

    with_audio = not args.no_audio
    headless = True if args.headless else None

    try:
        if args.query:
            asyncio.run(
                _run_session(
                    args.query,
                    with_audio=with_audio,
                    headless=headless,
                    max_steps=args.steps,
                )
            )
        else:
            asyncio.run(
                _interactive_loop(
                    with_audio=with_audio,
                    headless=headless,
                    max_steps=args.steps,
                )
            )
    finally:
        try:
            asyncio.run(close_client())
        except Exception:
            pass


if __name__ == "__main__":
    main()
