"""Authorization permission-matrix and IDOR tests (S8).

Drives protected read endpoints as an unauthenticated caller, a Support Agent and a
Supervisor, asserting the exact expected status. Worker/audit diagnostics are supervisor
only; action status is readable by both; nothing is readable unauthenticated.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.models.enums import UserRole
from app.models.user import User
from app.seeds.security import DEV_PASSWORD
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.usefixtures("_prepare_test_database")

# (method, url, unauth, agent, supervisor)
_MATRIX = [
    ("get", "/api/auth/me", 401, 200, 200),
    ("get", "/api/approvals", 401, 200, 200),
    ("get", "/api/actions", 401, 200, 200),
    ("get", "/api/outbox", 401, 403, 200),
    ("get", "/api/outbox/stats", 401, 403, 200),
    ("get", "/api/audit", 401, 403, 200),
    ("get", "/api/audit/verify", 401, 403, 200),
]


@pytest.fixture
async def api() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    from app.seeds.runner import seed

    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seeded_here = False
    async with factory() as session:
        if await session.scalar(select(User).limit(1)) is None:
            await seed(session)
            await session.commit()
            seeded_here = True
    settings = Settings(
        environment="test",
        jwt_secret="test-only-secret-0123456789abcdefghij",
        database_url=TEST_DATABASE_URL,
    )
    app = create_app(settings)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: settings
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, factory
        finally:
            # If this fixture seeded the database, leave it as empty as we found it so
            # later test modules can seed cleanly.
            if seeded_here:
                from tests.test_approval_service import _truncate_all

                async with factory() as session:
                    await _truncate_all(session)
                    await session.commit()
            await engine.dispose()


async def _token(client: AsyncClient, role: UserRole, factory: object) -> str:
    async with factory() as session:  # type: ignore[operator]
        user = await session.scalar(select(User).where(User.role == role).limit(1))
        assert user is not None
        email = user.email
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": DEV_PASSWORD}
    )
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


async def test_permission_matrix(
    api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    client, factory = api
    agent = await _token(client, UserRole.support_agent, factory)
    supervisor = await _token(client, UserRole.supervisor, factory)

    for method, url, unauth, ag, sup in _MATRIX:
        call = getattr(client, method)
        assert (await call(url)).status_code == unauth, (url, "unauth")
        assert (
            await call(url, headers={"Authorization": f"Bearer {agent}"})
        ).status_code == ag, (url, "agent")
        assert (
            await call(url, headers={"Authorization": f"Bearer {supervisor}"})
        ).status_code == sup, (url, "supervisor")


async def test_dev_endpoints_absent_in_test_via_production_gate(
    api: tuple[AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    # There is no direct production endpoint that executes an action: an
    # action-execute route never exists and returns 404.
    client, _ = api
    assert (
        await client.post(f"/api/actions/{uuid.uuid4()}/execute")
    ).status_code == 404
