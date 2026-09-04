import pytest

from cloud_waste.demo import main


async def test_demo_runs_end_to_end_without_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    await main()
    output = capsys.readouterr().out
    assert "part 1: unassociated Elastic IPs" in output
    assert "scanned the account -> 1 unassociated address(es) proposed" in output
    assert "part 2: idle EC2 instances" in output
    assert "scanned the account -> 1 idle instance(s) proposed" in output
    assert output.count("approved by a supervisor") == 2
    assert output.count("chain intact: True") == 2
