from __future__ import annotations

from main import build_parser


def test_paper_parser_accepts_alpaca_broker_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["paper", "--broker", "alpaca-paper"])
    assert args.command == "paper"
    assert args.broker == "alpaca-paper"


def test_check_alpaca_parser_accepts_base_url_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["check-alpaca", "--alpaca-base-url", "https://paper-api.alpaca.markets/v2"])
    assert args.command == "check-alpaca"
    assert args.alpaca_base_url.endswith("/v2")
