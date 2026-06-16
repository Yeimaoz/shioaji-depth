"""CLI arg-parsing tests — recorder constructed with parsed params, creds via env."""
from pathlib import Path


def test_cli_parses_args(monkeypatch):
    from shioaji_depth import cli

    captured = {}

    class FakeRec:
        def __init__(self, symbols, data_root, **kw):
            captured.update(symbols=symbols, data_root=data_root, kw=kw)

        async def run(self):
            pass

    monkeypatch.setattr(cli, "DepthRecorder", FakeRec)
    monkeypatch.setattr(cli.asyncio, "run", lambda coro: coro.close())
    cli.main(
        ["record", "--symbols", "MTX,TMF,TXF", "--data-root", "/tmp/twd",
         "--retention-days", "30"]
    )
    assert captured["symbols"] == ["MTX", "TMF", "TXF"]
    assert captured["data_root"] == Path("/tmp/twd")
    assert captured["kw"]["retention_days"] == 30
    assert captured["kw"]["flush_interval_s"] == 60  # default


def test_cli_diff_vol_flag(monkeypatch):
    from shioaji_depth import cli

    captured = {}

    class FakeRec:
        def __init__(self, symbols, data_root, **kw):
            captured.update(kw=kw)

        async def run(self):
            pass

    monkeypatch.setattr(cli, "DepthRecorder", FakeRec)
    monkeypatch.setattr(cli.asyncio, "run", lambda coro: coro.close())
    cli.main(["record", "--symbols", "MTX", "--data-root", "/tmp/twd", "--diff-vol"])
    assert captured["kw"]["record_diff_vol"] is True
