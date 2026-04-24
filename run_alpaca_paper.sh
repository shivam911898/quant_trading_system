#!/usr/bin/env bash
set -euo pipefail

cd /home/shivam/sys/quant_trading_system

/home/shivam/sys/quant_trading_system/.venv/bin/python main.py check-alpaca
/home/shivam/sys/quant_trading_system/.venv/bin/python main.py paper --broker alpaca-paper --strategy momentum --state-dir paper_runtime
