"""Input-validation hardening tests (S8)."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from app.core.validation import ensure_no_control_chars, has_control_chars
from app.main import create_app
from httpx import ASGITransport, AsyncClient


def test_control_char_detection() -> None:
    assert not has_control_chars("normal text\twith\nwhitespace")
    assert has_control_chars("bad\x07bell")
    assert has_control_chars("delete\x7fchar")
    with pytest.raises(ValueError, match="null bytes"):
        ensure_no_control_chars("a\x00b")
    with pytest.raises(ValueError, match="control characters"):
        ensure_no_control_chars("a\x1bescape")
    assert ensure_no_control_chars("clean@example.com") == "clean@example.com"


@pytest.mark.asyncio
async def test_login_rejects_control_chars_with_422() -> None:
    app = create_app(
        Settings(environment="test", jwt_secret="test-secret-0123456789abcdef")
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            json={"email": "a@b.com\x00", "password": "hunter2"},
        )
    # Rejected cleanly by validation, not processed.
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_rejects_oversize_field() -> None:
    app = create_app(
        Settings(environment="test", jwt_secret="test-secret-0123456789abcdef")
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            json={"email": "a@b.com", "password": "x" * 5000},
        )
    assert response.status_code == 422
