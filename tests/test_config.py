from talkto_ai.config import Config, LLMProvider, _parse_int


def test_parse_int_valid():
    assert _parse_int("20", 15, "TEST") == 20


def test_parse_int_invalid():
    assert _parse_int("invalid_number", 15, "TEST") == 15


def test_provider_availability():
    prov = LLMProvider(
        name="test",
        base_url="http://localhost",
        api_key="secret",
        model="test-model",
    )
    assert prov.is_available is True

    empty_prov = LLMProvider(
        name="empty",
        base_url="http://localhost",
        api_key="",
        model="test-model",
    )
    assert empty_prov.is_available is False


def test_config_available_providers():
    cfg = Config(
        providers=[
            LLMProvider("p1", "http://p1", "k1", "m1", supports_vision=False),
            LLMProvider("p2", "http://p2", "k2", "m2", supports_vision=True),
            LLMProvider("p3", "http://p3", "", "m3", supports_vision=True),
        ]
    )
    assert len(cfg.available_providers()) == 2
    assert len(cfg.available_providers(vision=True)) == 1
    assert cfg.available_providers(vision=True)[0].name == "p2"

