from __future__ import annotations

from main import main


def test_cli_smoke_command_returns_success() -> None:
    rc = main(["smoke-test"])
    assert rc == 0
