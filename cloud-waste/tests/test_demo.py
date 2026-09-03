import pytest

from cloud_waste.demo import main


async def test_demo_runs_end_to_end_without_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await main()
    output = capsys.readouterr().out
    assert "scanned the account" in output
    assert "approved by a supervisor" in output
    assert "executed" in output
    assert "chain intact: True" in output
