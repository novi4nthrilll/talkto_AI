# AI Web Agent

Program berbasis AI yang mencari informasi di internet dengan membuka browser sendiri, lalu menjawab dalam bentuk **teks** dan **audio**. Kalau ketemu captcha, program berhenti dan menunggu pengguna menyelesaikannya secara manual.

> Status: tahap perancangan konsep.

## Tujuan

1. Memakai LLM lewat API gratis (free tier).
2. Mengambil informasi dari internet secara otomatis lewat browser yang dikendalikan AI.
3. Melibatkan manusia saat ada hambatan seperti captcha atau 2FA.
4. Memberi jawaban dalam bentuk teks dan suara.

## Alur Kerja

````text
Perintah pengguna
      ↓
Modul LLM (otak)
      ↓
Browser agent (observe → think → act)
      ↓   ← ketemu captcha: pause, manusia solve, lanjut
Informasi terkumpul
      ↓
Modul rangkuman
      ↓
Teks  +  Modul suara (TTS) → file audio
````

## Komponen

### 1. Modul LLM (otak)

- Tugas utama: mengirim prompt ke API dan menerima jawaban.
- Banyak provider gratis memakai format yang sama (OpenAI-compatible), jadi cukup satu fungsi umum dan daftar provider di konfigurasi.
- **Fallback**: kalau satu provider kena rate limit, otomatis pindah ke provider berikutnya.
- Untuk agent yang perlu "melihat" halaman lewat screenshot, pilih model yang mendukung vision.

**Provider gratis yang bisa dipakai:** Google Gemini (AI Studio), Groq, OpenRouter (model `:free`), Mistral, Cloudflare Workers AI, Cohere, SambaNova. Semua ada batas request per menit atau per hari yang bisa berubah, jadi cek dashboard masing-masing.

### 2. Modul browser agent (tangan dan mata)

Bekerja dengan loop **observe → think → act**:

1. **Observe**: ambil kondisi halaman (teks inti, elemen yang bisa diklik, atau screenshot).
2. **Think**: kirim ke LLM, tanya langkah berikutnya untuk mencapai tujuan.
3. **Act**: eksekusi aksi dari LLM (buka URL, klik, ketik, scroll, atau selesai).
4. Ulangi sampai tugas selesai atau batas langkah tercapai.

Prinsip penting:

- **Batasi jumlah langkah** (misal 15-20) agar tidak looping dan tidak menghabiskan kuota API.
- **Bersihkan halaman** jadi teks inti sebelum dikirim ke LLM, karena token di free tier terbatas.
- **Pakai library yang sudah ada** (browser-use atau Playwright), jangan bikin kontrol browser dari nol.
- **Mode headful**: jendela browser terlihat sehingga pengguna bisa ikut campur.

### 3. Human-in-the-loop captcha

Agent harus sadar kapan buntu, lalu menyerahkan kendali ke manusia.

- **Deteksi**: di setiap siklus observe, cek tanda captcha (elemen captcha, teks "verify you are human", atau URL halaman challenge).
- **Pause**: loop berhenti total, LLM tidak boleh mencoba sendiri.
- **Notifikasi**: beri tanda jelas ke pengguna (pesan di terminal, bunyi, atau notifikasi).
- **Resume**: setelah pengguna selesai dan konfirmasi, agent mengambil kondisi halaman terbaru dan lanjut dari situ. Cookies dan tab tetap sama, tidak mulai dari awal.
- Captcha selalu diselesaikan manusia. Program tidak mencoba menembusnya secara otomatis.

### 4. Modul rangkuman

- Hasil yang terkumpul dikirim ke LLM dengan instruksi: **jawab berdasarkan data yang diambil, jangan mengarang, sebutkan sumber**.
- Atur gaya jawaban (bahasa Indonesia, singkat, santai). Kalimat pendek lebih enak saat didengar.

### 5. Modul suara (Text-to-Speech)

- Teks jawaban akhir diubah jadi file audio, lalu diputar atau disimpan.
- **Bersihkan teks dulu** dari simbol markdown, tabel, dan link panjang supaya tidak dibaca aneh.
- Pilih suara bahasa Indonesia. Untuk jawaban panjang, bacakan versi ringkasnya saja.

**Opsi TTS gratis:**

| Opsi | Catatan |
|---|---|
| edge-tts | Suara neural, ada suara Indonesia, library tidak resmi |
| gTTS | Paling simpel, kualitas standar |
| Piper | Jalan offline, tanpa internet |
| Gemini TTS | Cek limit gratisnya dulu |

## Teknologi (rencana)

| Komponen | Pilihan |
|---|---|
| Bahasa | Python |
| LLM | Gemini, Groq, OpenRouter |
| Browser automation | browser-use atau Playwright |
| Text-to-Speech | edge-tts (alternatif: gTTS, Piper) |

## Struktur Modul (rencana)

- **Utama**: menerima perintah dan menjalankan seluruh pipeline.
- **LLM**: client API dan logika fallback.
- **Browser agent**: kontrol browser dan deteksi captcha.
- **Rangkuman**: menyusun jawaban akhir dari data yang terkumpul.
- **Suara**: pembersihan teks dan pembuatan audio.
- **Konfigurasi**: daftar provider, batas langkah, pilihan suara.

## Catatan Penting

- **Rahasia**: API key disimpan di file environment, jangan ditulis di kode dan jangan di-commit.
- **Error handling**: siapkan jalan keluar untuk koneksi putus, halaman lambat, dan elemen tidak ketemu.
- **Logging**: catat setiap langkah agent untuk memudahkan debugging.
- **Etika**: patuhi Terms of Service dan `robots.txt`, hindari scraping berlebihan, dan jangan dipakai untuk login ke akun orang lain.
- **Ketergantungan**: free tier bisa berubah kapan saja. Karena itu fallback antar provider sangat disarankan.

## Roadmap

- [ ] 1. LLM dasar: tanya jawab lewat API
- [ ] 2. Tambah TTS: jawaban jadi suara
- [ ] 3. Browser sederhana: search satu halaman dan baca hasilnya
- [ ] 4. Loop multi-langkah (observe → think → act)
- [ ] 5. Deteksi captcha + pause/resume
- [ ] 6. Fallback antar provider dan perapihan
- [ ] 7. (Opsional) Input suara dan antarmuka web

## Lisensi

MIT
