import asyncio
from talkto_ai.router import RouteDecision, route_user_input


def test_route_decision_dataclass():
    d1 = RouteDecision(need_browser=False)
    assert d1.need_browser is False
    assert d1.search_query == ""

    d2 = RouteDecision(need_browser=True, search_query="berita terkini")
    assert d2.need_browser is True
    assert d2.search_query == "berita terkini"


def test_route_user_input_fast_path():
    for word in ["halo", "hai", "halo bro", "pagi", "tes"]:
        res = asyncio.run(route_user_input(word))
        assert res.need_browser is False
