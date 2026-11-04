from talkto_ai.tts import _truncate_for_speech, clean_text_for_speech


def test_clean_text_for_speech_markdown():
    raw = "### Halo Dunia!\nIni **teks tebal** dan *miring*. Kunjungi [Google](https://google.com) sekarang."
    cleaned = clean_text_for_speech(raw)
    assert "###" not in cleaned
    assert "**" not in cleaned
    assert "*" not in cleaned
    assert "https://google.com" not in cleaned
    assert "Google" in cleaned
    assert "Halo Dunia!" in cleaned


def test_clean_text_for_speech_bullets():
    raw = "- Poin satu\n* Poin dua\n• Poin tiga"
    cleaned = clean_text_for_speech(raw)
    assert "- " not in cleaned
    assert "* " not in cleaned
    assert "• " not in cleaned
    assert "Poin satu" in cleaned


def test_truncate_for_speech_short():
    short_text = "Ini adalah teks pendek."
    assert _truncate_for_speech(short_text, max_chars=100) == short_text


def test_truncate_for_speech_long():
    long_text = "Kalimat pertama. " * 50
    truncated = _truncate_for_speech(long_text, max_chars=100)
    assert len(truncated) <= 150
    assert truncated.endswith(" ... dan seterusnya.")


def test_play_and_cleanup_worker_deletes_file(tmp_path):
    import time
    from talkto_ai.tts import _play_and_cleanup_worker

    test_file = tmp_path / "dummy.mp3"
    test_file.write_text("dummy audio data")
    assert test_file.exists()

    # Gunakan command dummy yang cepat selesai (misal true atau python -c pass)
    _play_and_cleanup_worker(["true"], test_file, delete_after=True)
    assert not test_file.exists()


def test_play_and_cleanup_worker_keeps_file_if_disabled(tmp_path):
    from talkto_ai.tts import _play_and_cleanup_worker

    test_file = tmp_path / "keep.mp3"
    test_file.write_text("keep data")
    assert test_file.exists()

    _play_and_cleanup_worker(["true"], test_file, delete_after=False)
    assert test_file.exists()

