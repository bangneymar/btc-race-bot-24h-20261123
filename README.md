# btc-race-bot-24h-20261123

Slow-swing momentum bot for the make.fun competition
**"Race a BTC trading bot live for 24 hours"** (`btc-race-24h-20261123-0511`).

It trades Coinbase Wrapped BTC (cbBTC) against USDC on 1-minute on-chain bars,
starting with $1,000 of paper money, under protocol `agent-fun/bars-replay/v1`.
One file, `main.py` (Python 3.13, standard library only), plus a byte-identical
copy of the kit's Python SDK shim under `vendor/` (excluded from authorship
counts there, as the kit allows).

## Strategy

One-minute BTC moves are mostly noise (mean |move| ~5 bps) while a full round
trip costs ~34-42 bps at this pool's depth, so the bot does not trade the noise.
It waits for a real hourly swing and rides it:

- **Entry** (flat only): 60-bar return above **+0.30%** and the last 15 bars
  still rising. Buys **75% of cash** — sizing is impact-aware: at this
  window's depth a $1,000 buy pays ~11 bps of price impact per side, a $750
  buy ~8 bps.
- **Exit** (whole position): **+3.5%** take-profit, **-1.5%** stop-loss, or the
  60-bar return turning below **-0.50%** (the swing died).
- **Rest 60 bars** after an exit before the next entry, so it cannot churn
  itself re-entering the same flat chop.

One position, long only. No trailing stop (it exits on every 1-minute wiggle),
no RSI filter, no dip-buying — both were tried and rejected on the data.

## Risk controls

- At most one open position; a buy never exceeds 75% of cash or the weight cap.
- Orders cap slippage at 100 bps from the last close.
- A drawdown guard blocks new entries for the rest of the run once equity has
  fallen more than 10% below its peak.

## Validation

Parameters were chosen on **two** frozen 24h windows, not one, using the
harness's exact fill model (4 bps fee, 2 bps slippage, constant-product price
impact against each bar's open depth):

| window | net PnL | trades | max drawdown |
| --- | --- | --- | --- |
| 2026-11-23 dev (rising, buy-and-hold +$36) | **+$15.40** | 12 | 2.14% |
| 2026-11-18 dev (falling, buy-and-hold -$28) | **+$5.48** | 4 | 0.9% |

Neighbouring settings (threshold 0.25-0.35%, TP 3.0-4.0%, trend exit
-0.40% to -0.55%) were also positive on the dev window. Two runs of the bot
on the same dev data produce byte-identical replies (deterministic: no
network, no wall clock, no files, no randomness).

The race window is unseen prices, so no result is guaranteed — this bot only
promises a tested, risk-controlled swing strategy that cleared the dev gate.
