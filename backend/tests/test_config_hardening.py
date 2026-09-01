"""Production configuration safety-guard tests (S8 hardening)."""

from __future__ import annotations

import pytest
from app.core.config import DEV_ONLY_JWT_SECRET, Settings

_REAL_SECRET = "prod-secret-0123456789abcdefghijklmnop"


def _prod(**kw: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "jwt_secret": _REAL_SECRET,
        "debug": False,
        "backend_cors_origins": ["https://app.example.com"],
    }
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_production_boots_with_safe_config() -> None:
    settings = _prod()
    assert settings.environment == "production"


def test_production_refuses_dev_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        _prod(jwt_secret=DEV_ONLY_JWT_SECRET)


def test_production_refuses_short_secret() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        _prod(jwt_secret="short")


def test_production_refuses_debug() -> None:
    with pytest.raises(ValueError, match="DEBUG"):
        _prod(debug=True)


def test_production_refuses_wildcard_cors() -> None:
    with pytest.raises(ValueError, match="CORS"):
        _prod(backend_cors_origins=["*"])


def test_development_allows_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # The dev secret and debug are fine outside production. CI sets JWT_SECRET
    # globally for the app to use elsewhere in the job; clear it here so this test
    # exercises the real field default rather than whatever the ambient env holds.
    monkeypatch.delenv("JWT_SECRET", raising=False)
    settings = Settings(environment="development", debug=True)
    assert settings.jwt_secret == DEV_ONLY_JWT_SECRET
