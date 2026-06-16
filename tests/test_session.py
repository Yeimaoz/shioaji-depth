"""Session login tests — missing env raises; full creds call the SDK."""
import pytest

from shioaji_depth.session import ShioajiAuthError, login


def test_login_missing_env_raises(monkeypatch):
    for k in ("SHIOAJI_API_KEY", "SHIOAJI_SECRET", "SHIOAJI_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ShioajiAuthError):
        login()


def test_login_calls_sdk(monkeypatch):
    calls = {}

    class FakeApi:
        def login(self, api_key, secret_key):
            calls.update(api_key=api_key, secret_key=secret_key)

    import shioaji_depth.session as s

    monkeypatch.setattr(s.shioaji, "Shioaji", lambda: FakeApi())
    login(api_key="K", secret="S")
    assert calls == {"api_key": "K", "secret_key": "S"}


def test_login_accepts_secret_key_env(monkeypatch):
    calls = {}

    class FakeApi:
        def login(self, api_key, secret_key):
            calls.update(api_key=api_key, secret_key=secret_key)

    import shioaji_depth.session as s

    monkeypatch.delenv("SHIOAJI_SECRET", raising=False)
    monkeypatch.setenv("SHIOAJI_API_KEY", "EK")
    monkeypatch.setenv("SHIOAJI_SECRET_KEY", "ESK")  # doc-convention env name
    monkeypatch.setattr(s.shioaji, "Shioaji", lambda: FakeApi())
    login()
    assert calls == {"api_key": "EK", "secret_key": "ESK"}
