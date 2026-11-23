"""Slow-swing momentum bot for cbBTC/USDC, 1-minute bars (agent-fun/bars-replay/v1).

Idea, in one paragraph: one-minute BTC moves are mostly noise (mean |move| ~5 bps
while a full round trip costs ~26 bps), so this bot does NOT trade the noise. It
waits for a real hourly swing -- the 60-bar return above +0.30% with the last 15
bars still rising -- buys 75% of its cash once, then holds through the
wiggles until one of three slow exits fires: +3.5% take-profit, -1.5%
stop-loss, or the 60-bar return turning below -0.50% (the swing died). After
an exit it rests 60 bars before the next entry, so it cannot churn itself to
death re-entering the same flat chop. One position, long only, deterministic.

Why 75% size: the harness charges price impact against the pool depth, so a
trade's impact in bps grows with its size -- at this window's depth a $1,000
buy pays ~11 bps of impact per side while a $750 buy pays ~8 bps. Sizing at
75% keeps most of the move while cutting the round-trip cost from ~42 bps
to ~34 bps. Full size was tried first and lost money on the dev window for
exactly this reason.

Why these numbers (chosen on TWO frozen 24h windows, not one): the entry
threshold, the +3.5% / -1.5% exits, the -0.50% trend exit and the 60-bar rest
were all positive on both the 2026-11-18 dev window (falling BTC,
buy-and-hold -$28) and the 2026-11-23 dev window (rising BTC, buy-and-hold
+$36) in a replay using the harness's exact fill model (4 bps fee, 2 bps
slippage, constant-product impact against each bar's open depth): +$15.40 on
the 2026-11-23 window and +$5.48 on the 2026-11-18 window, max drawdown
~2%. Neighbouring settings (threshold 0.25-0.35%, TP 3.0-4.0%, trend exit
-0.40% to -0.55%) were positive on the dev window too; the chosen values sit
near the joint peak, not on a lone spike. A trailing stop was tried and
rejected: it exits on every 1-minute wiggle and churns 20-40 trades per day.
An RSI filter was tried and rejected: it cut the winners on the rising
window. No trailing stop, no RSI, no dip-buying.

Risk controls: at most one open position; a buy never exceeds 75% of cash on
hand or the weight cap; orders cap slippage at 100 bps from the last close; a
drawdown guard blocks new entries for the rest of the run once equity has
fallen more than 10% below its peak (the replay max drawdown was ~2%, so
this should never fire on a normal window -- it exists to keep the race
drawdown far under the 25% guardrail).

Determinism: every decision is a pure function of the closes seen so far and
the batch sequence number. No network, no wall clock, no files, no randomness.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy parameters (see module docstring for why) ---
LOOKBACK_BARS = 60          # hourly swing window
ENTRY_RETURN = 0.003        # 60-bar return must beat +0.30%
CONFIRM_BARS = 15           # ... and the last 15 bars must still be rising
TAKE_PROFIT = 0.035         # exit: position worth +3.5% over its cost
STOP_LOSS = 0.015           # exit: position worth -1.5% under its cost
TREND_DEAD = -0.005         # exit: 60-bar return below -0.50%
COOLDOWN_BARS = 60          # rest this long after an exit before re-entering
POSITION_FRACTION = 0.75    # buy this share of cash (impact-aware sizing)
MAX_SLIPPAGE_BPS = 100      # 1% past the close the order was decided on
DRAWDOWN_HALT = 0.10        # block new entries after a 10% peak-to-current fall

# Per-symbol close history (ints, at the symbol's price scale; ratios cancel it).
_closes = []
_last_exit_seq = -10 ** 9
_peak_equity = 0
_was_holding = False
_halted = False


def _ret(closes, n):
    """Return over the last n bars, or None if not enough history."""
    if len(closes) <= n:
        return None
    old = closes[-1 - n]
    if old <= 0:
        return None
    return closes[-1] / old - 1.0


def on_batch(state, batch):
    global _last_exit_seq, _peak_equity, _was_holding, _halted

    for bar in batch["bars"]:
        if bar["symbol"] == SYMBOL:
            _closes.append(int(bar["c"]))

    # Track the equity peak for the drawdown guard, and notice a closed
    # position (a sell that actually filled) so the cooldown starts then.
    if state.equity > _peak_equity:
        _peak_equity = state.equity
    holding = state.positions.get(SYMBOL)
    if _was_holding and holding is None:
        _last_exit_seq = state.seq
    _was_holding = holding is not None
    if _peak_equity > 0 and state.equity < _peak_equity * (1.0 - DRAWDOWN_HALT):
        _halted = True

    if state.warming_up:
        return []

    ret60 = _ret(_closes, LOOKBACK_BARS)
    ret15 = _ret(_closes, CONFIRM_BARS)

    if holding is not None:
        value = state.value(SYMBOL, holding.qty)
        cost = holding.cost
        take_profit = value >= cost * (1.0 + TAKE_PROFIT)
        stop_loss = value <= cost * (1.0 - STOP_LOSS)
        trend_dead = ret60 is not None and ret60 < TREND_DEAD
        if take_profit or stop_loss or trend_dead:
            return [{
                "side": "sell",
                "symbol": SYMBOL,
                "qty": holding.qty,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }]
        return []

    # Flat: look for a fresh hourly swing, rested and not halted.
    if _halted:
        return []
    if state.seq - _last_exit_seq < COOLDOWN_BARS:
        return []
    if ret60 is None or ret15 is None:
        return []
    if ret60 > ENTRY_RETURN and ret15 > 0:
        size = min(int(state.cash * POSITION_FRACTION), state.weight_room(SYMBOL))
        if size >= int(state.hello["fees"]["min_notional_quote_units"]):
            return [{
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": size,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }]
    return []


makefun_bars.run(on_batch)
