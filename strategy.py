"""
strategy.py — BNB DCA Grid Strategy Engine
Calibrated to BNB's actual volatility behaviour:
  - Daily avg swing: ±1.5–2.7%
  - Monthly volatility: ~5.1%
  - Support: $600 | Resistance: $680
  - Dip trigger: 2% | Take profit: 3.5% above avg cost
"""
import logging
from datetime import datetime, timedelta
from typing import Tuple
from config import (
    TRANCHE_LEVELS, TAKE_PROFIT_PCT, FEE_BUFFER_PCT,
    MAX_DEPLOY_PCT, ALERT_COOLDOWN_MIN, BNB_CONTEXT
)

logger = logging.getLogger(__name__)


class Signal:
    HOLD = "HOLD"
    BUY  = "BUY"
    SELL = "SELL"


class StrategyEngine:

    def evaluate(self, coin: str, current_price: float, state: dict) -> Tuple[str, dict]:
        baseline    = state.get("baseline_price")
        avg_cost    = state.get("avg_cost")
        deployed    = state.get("deployed_usdt", 0.0)
        total_fund  = state.get("total_fund", 500.0)
        tranche_lvl = state.get("tranche_level", 0)

        if baseline is None:
            return Signal.HOLD, {"reason": "No baseline yet — set on first fetch"}

        if self._in_cooldown(state):
            remaining = self._cooldown_remaining(state)
            return Signal.HOLD, {"reason": f"Cooldown: {remaining}m remaining"}

        deploy_pct = (deployed / total_fund * 100) if total_fund > 0 else 0

        # ── SELL CHECK (priority) ────────────────────────────
        if avg_cost and deployed > 0:
            required_sell = avg_cost * (1 + (TAKE_PROFIT_PCT + FEE_BUFFER_PCT) / 100)
            if current_price >= required_sell:
                gross_pct   = (current_price - avg_cost) / avg_cost * 100
                net_pct     = gross_pct - FEE_BUFFER_PCT
                usdt_return = deployed * (current_price / avg_cost)
                net_gain    = usdt_return - deployed

                # BNB market context for notification
                zone = self._price_zone(current_price)

                return Signal.SELL, {
                    "current_price":    current_price,
                    "avg_cost":         avg_cost,
                    "gross_profit_pct": round(gross_pct, 2),
                    "net_profit_pct":   round(net_pct, 2),
                    "deployed_usdt":    round(deployed, 2),
                    "usdt_return":      round(usdt_return, 2),
                    "net_gain_usdt":    round(net_gain, 2),
                    "take_profit_at":   round(required_sell, 2),
                    "fee_pct":          FEE_BUFFER_PCT,
                    "price_zone":       zone,
                }

        # ── BUY CHECK ────────────────────────────────────────
        if deploy_pct >= MAX_DEPLOY_PCT:
            return Signal.HOLD, {"reason": f"Max deploy reached ({deploy_pct:.1f}%)"}

        drop_pct = (baseline - current_price) / baseline * 100

        triggered_level = None
        for i, level in enumerate(TRANCHE_LEVELS):
            if drop_pct >= level["dip_pct"] and tranche_lvl <= i:
                triggered_level = level
                triggered_idx   = i
                break

        if triggered_level:
            tranche_usdt  = total_fund * (triggered_level["deploy_pct"] / 100)
            remaining_cap = total_fund * (MAX_DEPLOY_PCT / 100) - deployed

            if tranche_usdt > remaining_cap:
                tranche_usdt = remaining_cap
            if tranche_usdt < 5:
                return Signal.HOLD, {"reason": "Tranche too small (<$5)"}

            coin_units = tranche_usdt / current_price
            new_avg    = self._calc_new_avg(
                avg_cost, state.get("position_size", 0),
                current_price, tranche_usdt
            )

            # BNB-specific context
            near_support = current_price <= BNB_CONTEXT["support_strong"] * 1.02
            zone         = self._price_zone(current_price)
            sell_target  = new_avg * (1 + (TAKE_PROFIT_PCT + FEE_BUFFER_PCT) / 100)

            urgency = "🔥 Strong buy — near key support" if near_support else "📊 Normal dip — standard buy"

            return Signal.BUY, {
                "current_price":     current_price,
                "baseline_price":    baseline,
                "drop_pct":          round(drop_pct, 2),
                "tranche_level":     tranche_lvl + 1,
                "tranche_usdt":      round(tranche_usdt, 2),
                "coin_units":        round(coin_units, 6),
                "deployed_usdt":     round(deployed, 2),
                "remaining_usdt":    round(remaining_cap - tranche_usdt, 2),
                "total_fund":        total_fund,
                "deploy_pct_after":  round((deployed + tranche_usdt) / total_fund * 100, 1),
                "avg_cost_after":    new_avg,
                "sell_target":       round(sell_target, 2),
                "price_zone":        zone,
                "urgency":           urgency,
                "near_support":      near_support,
            }

        # Determine how far to next trigger
        next_trigger = None
        for i, level in enumerate(TRANCHE_LEVELS):
            if tranche_lvl <= i:
                next_trigger = level["dip_pct"]
                break

        gap = round((next_trigger - drop_pct), 2) if next_trigger else None
        return Signal.HOLD, {
            "reason": f"Watching | drop {drop_pct:.2f}% | need {next_trigger}% | gap {gap}%"
        }

    def _price_zone(self, price: float) -> str:
        ctx = BNB_CONTEXT
        if price >= ctx["resistance"]:
            return "above resistance — good sell zone"
        elif price >= (ctx["support_strong"] + ctx["resistance"]) / 2:
            return "mid-range — neutral"
        elif price >= ctx["support_strong"]:
            return "near support — buy zone"
        elif price >= ctx["range_2026_low"]:
            return "below support — deep buy zone"
        else:
            return "below 2026 low — extreme caution"

    def _calc_new_avg(self, current_avg, current_units, new_price, new_usdt):
        new_units    = new_usdt / new_price
        total_units  = (current_units or 0) + new_units
        total_cost   = ((current_avg or new_price) * (current_units or 0)) + new_usdt
        if total_units == 0:
            return new_price
        return round(total_cost / total_units, 4)

    def _in_cooldown(self, state: dict) -> bool:
        last = state.get("last_alert_time")
        if not last:
            return False
        try:
            elapsed = datetime.utcnow() - datetime.fromisoformat(last)
            return elapsed < timedelta(minutes=ALERT_COOLDOWN_MIN)
        except:
            return False

    def _cooldown_remaining(self, state: dict) -> int:
        last = state.get("last_alert_time")
        if not last:
            return 0
        try:
            elapsed = datetime.utcnow() - datetime.fromisoformat(last)
            remaining = timedelta(minutes=ALERT_COOLDOWN_MIN) - elapsed
            return max(0, int(remaining.total_seconds() / 60))
        except:
            return 0
