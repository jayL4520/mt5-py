# MT5 Quant System

Python-based quantitative trading system for MetaTrader 5.

## Features

- MT5 connection and account login
- Historical bar download
- Strategy interface with two implementations
- Risk-based position sizing
- Market order execution
- Local backtesting
- Trading window and daily risk guardrails
- Backtest report export

## Included strategies

- `ma_cross_atr`: generic moving-average crossover with ATR stop
- `xau_m1_momentum`: XAUUSD M1 trend-breakout momentum strategy

The default XAUUSD M1 setup uses:

- Symbol: `XAUUSD`
- Timeframe: `M1`
- Take profit: `+0.3%`
- Stop loss: `-0.4%`
- Risk per trade: configurable fixed percentage

## Install

```bash
pip install -e .
```

## Config

Use [config.xauusd.m1.yaml](C:\Users\A\Documents\Codex\2026-05-14\mt5\config.xauusd.m1.yaml) for the gold setup.

Important fields:

- `trading.symbol`
- `trading.timeframe`
- `strategy.risk_per_trade`
- `strategy.take_profit_pct`
- `strategy.stop_loss_pct`
- `safety.trading_windows`
- `safety.max_daily_loss_pct`
- `safety.max_consecutive_losses`

## Run

Backtest with MT5 history:

```bash
mt5-quant backtest --config config.xauusd.m1.yaml --bars 5000
```

Backtest and export reports to a custom folder:

```bash
mt5-quant backtest --config config.xauusd.m1.yaml --bars 5000 --report-dir reports\\run_001
```

Run live trading:

```bash
mt5-quant live --config config.xauusd.m1.yaml
```

## XAUUSD M1 logic

Entry conditions:

- fast EMA above slow EMA for long trend, below for short trend
- close breaks recent high or low over the configured lookback window
- RSI confirms momentum

Exit conditions:

- take profit at `+0.3%`
- stop loss at `-0.4%`
- early close when trend or momentum weakens

## Guardrails

The live and backtest engines now enforce:

- trading window filter
- daily loss stop
- consecutive loss stop

Default values in the sample config:

- trading window: `14:00-02:00` in `Asia/Shanghai`
- max daily loss: `2%`
- max consecutive losses: `3`

## Backtest outputs

Backtests export files into `reporting.output_dir`:

- `summary.json`
- `trades.csv`
- `equity_curve.csv`

The summary now includes:

- net profit
- win rate
- gross profit and gross loss
- average trade, win, and loss
- profit factor
- max drawdown percentage
- blocked entry counts by risk rule

## Notes

- Validate symbol contract size, tick value, and lot step with your broker before live trading.
- Keep API credentials out of version control.
- Run on demo first and inspect slippage during London and New York sessions.
