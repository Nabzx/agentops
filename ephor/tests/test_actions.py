import uuid
from datetime import UTC, datetime

from ephor.actions import InMemoryProposalStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def test_create_returns_a_proposal_with_a_fresh_id() -> None:
    store = InMemoryProposalStore()
    proposal = await store.create(
        action_type="retry_charge",
        parameters={"amount_pence": 4700},
        risk_level="medium",
        evidence={"decline_code": "insufficient_funds"},
        created_at=NOW,
    )
    assert isinstance(proposal.id, uuid.UUID)
    assert proposal.action_type == "retry_charge"
    assert proposal.parameters == {"amount_pence": 4700}


async def test_get_returns_none_for_an_unknown_id() -> None:
    store = InMemoryProposalStore()
    assert await store.get(uuid.uuid4()) is None


async def test_get_returns_the_created_proposal() -> None:
    store = InMemoryProposalStore()
    created = await store.create(
        action_type="retry_charge",
        parameters={},
        risk_level="low",
        evidence={},
        created_at=NOW,
    )
    fetched = await store.get(created.id)
    assert fetched == created


async def test_list_by_action_type_filters_and_orders_by_creation() -> None:
    store = InMemoryProposalStore()
    first = await store.create(
        action_type="retry_charge",
        parameters={},
        risk_level="low",
        evidence={},
        created_at=NOW,
    )
    await store.create(
        action_type="send_dunning",
        parameters={},
        risk_level="low",
        evidence={},
        created_at=NOW,
    )
    second = await store.create(
        action_type="retry_charge",
        parameters={},
        risk_level="low",
        evidence={},
        created_at=NOW,
    )

    only_retries = await store.list_by_action_type("retry_charge")
    assert [p.id for p in only_retries] == [first.id, second.id]
