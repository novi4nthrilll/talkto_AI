# AI Web Agent

Program berbasis AI yang mencari informasi di internet dengan membuka browser sendiri, lalu menjawab dalam bentuk **teks** dan **audio**. Kalau ketemu captcha, program berhenti dan menunggu pengguna menyelesaikannya secara manual.

> **Status**: Selesai diimplementasikan & siap digunakan!

---

## Fitur Utama

1. **Multi-LLM dengan Fallback Otomatis**: Mendukung Gemini (AI Studio), Groq, dan OpenRouter (model free). Jika satu provider limit/error, otomatis pindah ke provider berikutnya dengan mekanisme retry.
2. **Browser Agent Cerdas**: Siklus *observe → think → act* menggunakan Playwright. Elemen interaktif ditandai langsung di DOM browser (`data-talkto-id`) sehingga akurat dan tidak meleset.
3. **Human-in-the-Loop Captcha**: Deteksi akurat (Cloudflare Turnstile, reCAPTCHA, hCaptcha, iframe challenge). Program otomatis pause, memberi notifikasi di terminal, dan menunggu pengguna menyelesaikan captcha di browser sebelum lanjut.
4. **Rangkuman Cerdas**: LLM merangkum data yang diambil secara faktual, menyebutkan sumber, dalam bahasa Indonesia yang ringkas dan santai.
5. **Text-to-Speech (TTS)**: Pembersihan markdown otomatis, teks dibacakan menggunakan `edge-tts` (suara neural Indonesia yang natural) atau `gTTS`, lalu diputar otomatis dan disimpan ke folder `output/`.

---

## Instalasi

### 1. Clone & Masuk ke Folder
```bash
git clone https://github.com/novi4nth/talkto_AI.git
cd talkto_AI
```

### 2. Buat Virtual Environment & Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate

# Install package
pip install -e .
# Atau: pip install -r requirements.txt

# Install browser Playwright
playwright install chromium
```

### 3. Konfigurasi API Key
Salin template konfigurasi:
```bash
cp .env.example .env
```
Buka `.env` dan isi minimal satu API key:
- **`GEMINI_API_KEY`**: Dapatkan gratis di [Google AI Studio](https://aistudio.google.com/)
- **`GROQ_API_KEY`**: Dapatkan gratis di [Groq Console](https://console.groq.com/)
- **`OPENROUTER_API_KEY`**: Dapatkan gratis di [OpenRouter](https://openrouter.ai/)

---

## Cara Penggunaan

### 1. Mode Interaktif (Prompt Chat)
```bash
talkto
# Atau: python -m talkto_ai
```

### 2. Mode Perintah Langsung (CLI Argument)
```bash
talkto "Siapa presiden Indonesia saat ini?"
```

### 3. Opsi Tambahan
```bash
# Tanpa suara (hanya teks)
talkto "Harga emas hari ini" --no-audio

# Mode headless (browser tidak ditampilkan)
talkto "Kapan gerhana matahari berikutnya?" --headless

# Batasi langkah browsing (misal maksimal 8 langkah)
talkto "Berita terkini teknologi AI" --steps 8
```

---

## Struktur Modul

```
talkto_AI/
├── .env.example          # Template konfigurasi environment
├── .gitignore            # Mengabaikan .env, cache, output audio
├── pyproject.toml        # Metadata proyek & build config
├── requirements.txt      # Daftar dependency pip
├── requirements-dev.txt  # Dependency pengujian (pytest)
├── README.md             # Dokumentasi utama
├── tests/                # Unit tests (16 tests, 100% lulus)
│   ├── test_config.py
│   ├── test_llm.py
│   ├── test_tts.py
│   └── test_browser_agent.py
└── talkto_ai/
    ├── __init__.py       # Package exports & version
    ├── __main__.py      # Entry point `python -m talkto_ai`
    ├── config.py         # Konfigurasi terpusat dari .env
    ├── llm.py            # Client OpenAI-compatible, shared HTTP, fallback
    ├── browser_agent.py  # Agent Playwright, DOM tag injection, captcha pause
    ├── summarizer.py     # Prompt rangkuman faktual & santai
    ├── tts.py            # edge-tts & gTTS async, player multi-platform
    └── main.py           # CLI runner & prompt loop
```

---

## Pengujian (Testing)

Jalankan test suite menggunakan `pytest`:
```bash
pytest tests/
```

---

## Roadmap

- [x] 1. LLM dasar: tanya jawab lewat API OpenAI-compatible
- [x] 2. Tambah TTS: teks jawaban jadi audio (edge-tts / gTTS)
- [x] 3. Browser agent dasar: buka halaman, navigasi, dan ekstrak teks
- [x] 4. Loop multi-langkah (observe → think → act) dengan DOM tag injection
- [x] 5. Deteksi captcha akurat + mekanisme pause/resume interaktif
- [x] 6. Fallback antar provider, retry pada rate limit, dan CLI flags
- [ ] 7. (Opsional) Input suara langsung (STT) dan antarmuka GUI / Web UI

---

## Lisensi

[MIT](LICENSE)
