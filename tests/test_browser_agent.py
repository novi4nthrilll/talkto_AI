from talkto_ai.browser_agent import (
    _clean_html,
    _parse_agent_response,
    _trim_messages,
)


def test_clean_html():
    html = """
    <html>
      <head><title>Test</title><script>alert(1);</script><style>body { color: red; }</style></head>
      <body>
        <header>Header Bar</header>
        <main>
          <h1>Judul Utama</h1>
          <p>Paragraf informasi penting.</p>
        </main>
        <footer>Footer copyright</footer>
      </body>
    </html>
    """
    cleaned = _clean_html(html)
    assert "alert(1)" not in cleaned
    assert "body { color: red; }" not in cleaned
    assert "Header Bar" not in cleaned
    assert "Footer copyright" not in cleaned
    assert "Judul Utama" in cleaned
    assert "Paragraf informasi penting." in cleaned


def test_parse_agent_response_clean_json():
    text = '{"thought": "Mencari info", "action": "goto https://example.com", "extract": "Data"}'
    parsed = _parse_agent_response(text)
    assert parsed["thought"] == "Mencari info"
    assert parsed["action"] == "goto https://example.com"
    assert parsed["extract"] == "Data"


def test_parse_agent_response_markdown_fence():
    text = """```json
{"thought": "Klik link", "action": "click 2", "extract": ""}
```"""
    parsed = _parse_agent_response(text)
    assert parsed["thought"] == "Klik link"
    assert parsed["action"] == "click 2"


def test_parse_agent_response_fallback():
    text = "Buka website ini"
    parsed = _parse_agent_response(text)
    assert parsed["thought"] == text
    assert parsed["action"] == "done"


def test_trim_messages():
    messages = [{"role": "system", "content": "system prompt"}]
    # Add 12 user/assistant messages
    for i in range(12):
        messages.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})

    trimmed = _trim_messages(messages, keep_recent=4)
    # Harus ada system msg, tujuan awal, ringkasan, dan 4 pesan terakhir
    assert trimmed[0]["role"] == "system"
    assert trimmed[1]["content"] == "msg 0"
    assert "diringkas" in trimmed[2]["content"]
    assert len(trimmed) == 1 + 1 + 1 + 4

