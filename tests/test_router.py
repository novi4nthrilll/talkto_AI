import pytest
from talkto_ai.router import RouteDecision


def test_route_decision_dataclass():
    d1 = RouteDecision(need_browser=False, direct_reply="Halo!")
    assert d1.need_browser is False
    assert d1.direct_reply == "Halo!"
    assert d1.search_query == ""

    d2 = RouteDecision(need_browser=True, search_query="berita terkini")
    assert d2.need_browser is True
    assert d2.search_query == "berita terkini"

