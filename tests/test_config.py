import pytest

from helpdesk.config import Settings


def test_backend_defaults_to_local(monkeypatch):
    monkeypatch.setattr("helpdesk.config.load_dotenv", lambda **kwargs: None)
    monkeypatch.delenv("APP_BACKEND", raising=False)
    assert Settings().backend == "local"
    assert Settings.from_env().backend == "local"


@pytest.mark.parametrize("backend", ["local", "remote"])
def test_supported_backends(monkeypatch, backend):
    monkeypatch.setenv("APP_BACKEND", backend)
    assert Settings.from_env().backend == backend


@pytest.mark.parametrize("backend", ["demo", "invalid", ""])
def test_unsupported_backends_fail_at_configuration(monkeypatch, backend):
    monkeypatch.setenv("APP_BACKEND", backend)
    with pytest.raises(ValueError, match="APP_BACKEND は local / remote"):
        Settings.from_env()
