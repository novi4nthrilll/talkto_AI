from talkto_ai.llm import build_user_message, encode_screenshot


def test_build_user_message_text_only():
    msg = build_user_message("Halo AI")
    assert msg == {"role": "user", "content": "Halo AI"}


def test_build_user_message_with_image():
    msg = build_user_message("Lihat gambar ini", image_b64="abc123xyz")
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    assert msg["content"][0]["text"] == "Lihat gambar ini"
    assert "data:image/png;base64,abc123xyz" in msg["content"][1]["image_url"]["url"]


def test_encode_screenshot():
    raw_bytes = b"hello image binary"
    encoded = encode_screenshot(raw_bytes)
    assert isinstance(encoded, str)
    assert len(encoded) > 0

