"""
Main — entry point AI Web Agent.

Alur: perintah pengguna → browser agent → rangkuman → teks + suara.
"""

from __future__ import annotations

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
    Pakai asyncio.to_thread supaya tidak block event loop.
    """
    await asyncio.to_thread(input)
    agent.resume_after_captcha()


async def _run_session(query: str) -> None:
    """Jalankan satu sesi pencarian."""
    console.print(f"\n[bold green]🔍 Mencari:[/] {query}\n")

    agent = BrowserAgent()

    # Task untuk handle captcha input secara async
    captcha_task: asyncio.Task | None = None

    def _captcha_handler(message: str) -> None:
        nonlocal captcha_task
        _on_captcha(message)
        # Spawn async task untuk tunggu Enter, bukan thread biasa
        captcha_task = asyncio.create_task(_wait_for_captcha_input(agent))

    # Jalankan agent
    use_vision = bool(config.available_providers(vision=True))
    result = await agent.run(
        goal=query,
        on_step=_on_step,
        on_captcha=_captcha_handler,
        use_vision=use_vision,
    )

    # Cleanup captcha task kalau masih jalan
    if captcha_task and not captcha_task.done():
        captcha_task.cancel()

    if result.state == AgentState.ERROR:
        console.print(f"\n[bold red]❌ Error:[/] {result.error}")
        return

    # Rangkuman langkah
    steps_summary = "\n".join(
        f"- Langkah {s.step}: {s.thought[:60]} → {s.action}" for s in result.steps
    )

    # Rangkum jawaban
    console.print("\n[bold cyan]📝 Merangkum jawaban...[/]")
    answer = await summarize(query, result.collected_text, steps_summary)

    # Tampilkan jawaban
    console.print(Panel(answer, title="💬 Jawaban", border_style="green"))

    # Text-to-Speech
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


def main() -> None:
    """Entry point CLI."""
    _setup_logging()
    _print_banner()

    # Cek provider
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

    # Loop interaktif
    try:
        while True:
            try:
                query = Prompt.ask("[bold cyan]Tanya[/]")
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Bye! 👋[/]")
                break

            query = query.strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "keluar"):
                console.print("[dim]Bye! 👋[/]")
                break

            asyncio.run(_run_session(query))
    finally:
        # Cleanup shared HTTP client
        try:
            asyncio.run(close_client())
        except Exception:
            pass


if __name__ == "__main__":
    main()
