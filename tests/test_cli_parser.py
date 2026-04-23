from __future__ import annotations

from main import build_parser


def test_paper_parser_accepts_alpaca_broker_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["paper", "--broker", "alpaca-paper"])
    assert args.command == "paper"
    assert args.broker == "alpaca-paper"
