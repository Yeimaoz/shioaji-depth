"""Contract resolution: shortcode -> rolling front-month (R1) leaf."""
from shioaji_depth.contracts import resolve_contract


class _Leaf:
    def __init__(self, code):
        self.code = code


class _Group(dict):
    def __getattr__(self, k):
        return self[k]


def _fake_api():
    class A:
        pass

    api = A()
    api.Contracts = type("C", (), {})()
    api.Contracts.Futures = type("F", (), {})()
    api.Contracts.Futures.MXF = _Group(MXFR1=_Leaf("MXFR1"))
    api.Contracts.Futures.TXF = _Group(TXFR1=_Leaf("TXFR1"))
    api.Contracts.Futures.TMF = _Group(TMFR1=_Leaf("TMFR1"))
    return api


def test_resolve_shortcodes():
    api = _fake_api()
    assert resolve_contract(api, "MTX").code == "MXFR1"
    assert resolve_contract(api, "TXF").code == "TXFR1"
    assert resolve_contract(api, "TMF").code == "TMFR1"


def test_resolve_unknown_raises():
    api = _fake_api()
    try:
        resolve_contract(api, "NOPE")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown contract")
