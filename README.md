# Quant Trading System

## Setup
```bash
cd quant_trading_system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment configuration (optional)
Defaults are production-safe for local paper runs and can be overridden with env vars:

- `QTS_LOG_LEVEL` (default: `INFO`)
- `QTS_LOG_FILE` (default: `logs/system.log`)
- `QTS_STATE_DIR` (default: `paper_runtime`)
- `QTS_DASHBOARD_PORT` (default: `8501`)
- `QTS_DASHBOARD_HOST` (default: `127.0.0.1`)
- `QTS_INITIAL_CAPITAL` (default: `10000`)
- `QTS_POSITION_SIZE` (default: `0.95`)
- `QTS_COMMISSION_PCT` (default: `0.001`)
- `QTS_SLIPPAGE_PCT` (default: `0.0005`)
- `QTS_STOP_LOSS_PCT` (default: `0.05`)
- `QTS_TAKE_PROFIT_PCT` (default: `0.10`)
- `QTS_PAPER_STARTING_CASH` (default: `10000`)
- `QTS_PAPER_COMMISSION_PCT` (default: `0.001`)
- `QTS_PAPER_SLIPPAGE_PCT` (default: `0.0005`)
- `QTS_PAPER_WARMUP_BARS` (default: `220`)
- `QTS_PAPER_BROKER` (default: `simulated`; options: `simulated`, `alpaca-paper`)
- `ALPACA_API_KEY` (required for `alpaca-paper`)
- `ALPACA_SECRET_KEY` (required for `alpaca-paper`)
- `ALPACA_BASE_URL` (default: `https://paper-api.alpaca.markets`)

## Run
Backtest:
```bash
python main.py backtest
```

Paper trading:
```bash
python main.py paper
```

Paper trading with Alpaca Paper API:
```bash
python main.py paper --broker alpaca-paper
```

Or pass credentials explicitly:
```bash
python main.py paper --broker alpaca-paper --alpaca-api-key <KEY> --alpaca-secret-key <SECRET>
```

Dashboard:
```bash
python main.py dashboard
```

Smoke test:
```bash
python main.py smoke-test
```

Validate Alpaca paper credentials:
```bash
python main.py check-alpaca
```

## Tests
```bash
pytest
```

## Lint and type-check
```bash
ruff check .
mypy
```

## CI
GitHub Actions workflow is available at `.github/workflows/ci.yml` and enforces blocking gates on push/PR:

- `ruff check .`
- `mypy`
- `pytest`

## Strategy selection
```bash
python main.py backtest --strategy mean_reversion
python main.py backtest --strategy momentum
python main.py backtest --strategy combined

python main.py paper --strategy mean_reversion
python main.py paper --strategy momentum
python main.py paper --strategy combined
```
