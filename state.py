"""
state.py — Persistent state management
Tracks per-coin: baseline price, average cost, deployed capital, tranche level
"""
import copy
import json
import os
import tempfile
import threading
from datetime import datetime
from config import STATE_FILE, COINS, FUND_PER_COIN


DEFAULT_COIN_STATE = {
    "baseline_price":   None,   # price anchor — dip % is measured from here
    "avg_cost":         None,   # weighted average buy price across tranches
    "deployed_usdt":    0.0,    # total USDT deployed into this coin
    "total_fund":       0.0,    # total USDT allocated to this coin
    "tranche_level":    0,      # how many tranche levels triggered so far
    "last_buy_price":   None,   # price of most recent buy
    "position_size":    0.0,    # estimated coin units held (for display only)
    "last_alert_time":  None,   # ISO timestamp of last alert (any type)
    "last_alert_type":  None,   # "BUY" or "SELL"
    "pending_action":   None,   # pending button-confirmable action
    "trades":           [],     # list of trade alerts sent
}


def _fresh_coin_state():
    return copy.deepcopy(DEFAULT_COIN_STATE)


class StateManager:
    def __init__(self):
        self.state = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        with self._lock:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
            # Ensure all coins have state
            for coin in COINS:
                if coin not in self.state:
                    self.state[coin] = _fresh_coin_state()
                    self.state[coin]["total_fund"] = FUND_PER_COIN.get(coin, 500)
            self._save()

    def _save(self):
        with self._lock:
            state_dir = os.path.dirname(STATE_FILE) or "."
            fd, tmp_path = tempfile.mkstemp(prefix=".bot_state.", suffix=".tmp", dir=state_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, STATE_FILE)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

    def get(self, coin):
        with self._lock:
            return copy.deepcopy(self.state.get(coin, _fresh_coin_state()))

    def update(self, coin, updates: dict):
        with self._lock:
            if coin not in self.state:
                self.state[coin] = _fresh_coin_state()
            self.state[coin].update(updates)
            self._save()

    def set_baseline(self, coin, price):
        self.update(coin, {"baseline_price": price})

    def set_pending_action(self, coin, action: dict | None):
        self.update(coin, {"pending_action": action})

    def record_buy_alert(self, coin, price, usdt_amount):
        """Update state after a BUY alert is sent (user will execute manually)"""
        with self._lock:
            cs = self.state[coin]
            prev_deployed = cs["deployed_usdt"]
            prev_units = cs["position_size"]

            new_units = usdt_amount / price
            total_units = prev_units + new_units
            total_deployed = prev_deployed + usdt_amount

            # Weighted average cost
            if total_units > 0:
                new_avg = total_deployed / total_units
            else:
                new_avg = price

            self.state[coin].update({
                "avg_cost":        round(new_avg, 6),
                "deployed_usdt":   round(total_deployed, 2),
                "last_buy_price":  price,
                "position_size":   round(total_units, 8),
                "tranche_level":   cs["tranche_level"] + 1,
                "baseline_price":  price,   # new floor after each buy
                "last_alert_time": datetime.utcnow().isoformat(),
                "last_alert_type": "BUY",
                "pending_action":  None,
            })
            self._append_trade(coin, "BUY", price, usdt_amount)

    def record_sell_alert(self, coin, price):
        """Reset coin state after a SELL alert is sent"""
        with self._lock:
            cs = self.state[coin]
            deployed = cs["deployed_usdt"]
            avg_cost = cs["avg_cost"] or price
            profit_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost else 0

            self._append_trade(coin, "SELL", price, deployed, profit_pct)

            # Reset position — stable coins back in wallet
            self.state[coin].update({
                "baseline_price":  price,
                "avg_cost":        None,
                "deployed_usdt":   0.0,
                "position_size":   0.0,
                "tranche_level":   0,
                "last_buy_price":  None,
                "last_alert_time": datetime.utcnow().isoformat(),
                "last_alert_type": "SELL",
                "pending_action":  None,
            })
            self._save()

    def _append_trade(self, coin, action, price, amount, profit_pct=None):
        with self._lock:
            trade = {
                "time":   datetime.utcnow().isoformat(),
                "action": action,
                "price":  price,
                "amount": amount,
            }
            if profit_pct is not None:
                trade["profit_pct"] = round(profit_pct, 2)
            self.state[coin]["trades"].append(trade)
            self._save()

    def all_coins(self):
        with self._lock:
            return {coin: copy.deepcopy(self.state[coin]) for coin in COINS}

    def reset_coin(self, coin, current_price):
        """Manually reset a coin's baseline (call on startup or manual override)"""
        with self._lock:
            self.state[coin] = _fresh_coin_state()
            self.state[coin]["total_fund"] = FUND_PER_COIN.get(coin, 500)
            self.state[coin]["baseline_price"] = current_price
            self._save()
