"""
telegram_handler.py — Two-way Telegram conversation handler
Polls for incoming user messages and processes commands.

Supported replies:
  bought <price>        — confirm buy at actual price (e.g. "bought 617.20")
  bought <price> <amt>  — confirm buy with custom USDT amount (e.g. "bought 617 45")
  sold <price>          — confirm sell at actual price (e.g. "sold 639.50")
  skip                  — skip this signal, update baseline to current price
  status                — get current position summary
  reset                 — reset all state, start fresh
  pause                 — pause alerts for 2 hours
  resume                — resume alerts
  help                  — show all commands
"""
import html
import math
import requests
import logging
import threading
import time
from datetime import datetime, timedelta
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BNB_CONTEXT

logger = logging.getLogger(__name__)

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class TelegramHandler:

    def __init__(self, state_manager, notifier):
        self.state    = state_manager
        self.notifier = notifier
        self.offset   = None       # Telegram update offset
        self.paused_until = None   # datetime if paused
        self._running = False
        self._thread  = None

    # ── Public controls ──────────────────────────────────────

    def start(self):
        """Start polling for messages in a background thread."""
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Telegram message handler started.")

    def stop(self):
        self._running = False

    def is_paused(self) -> bool:
        if self.paused_until and datetime.utcnow() < self.paused_until:
            return True
        self.paused_until = None
        return False

    # ── Polling loop ─────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                logger.error(f"Poll error: {e}")
            time.sleep(3)   # poll every 3 seconds

    def _get_updates(self) -> list:
        params = {"timeout": 2, "allowed_updates": ["message", "callback_query"]}
        if self.offset:
            params["offset"] = self.offset
        try:
            r = requests.get(f"{TELEGRAM_URL}/getUpdates", params=params, timeout=10)
            r.raise_for_status()
            data    = r.json()
            updates = data.get("result", [])
            if updates:
                self.offset = updates[-1]["update_id"] + 1
            return updates
        except Exception as e:
            logger.error(f"getUpdates error: {e}")
            return []

    def _handle_update(self, update: dict):
        callback = update.get("callback_query")
        if callback:
            self._handle_callback(callback)
            return

        msg = update.get("message", {})
        if not msg:
            return

        # Only accept commands from the configured private chat.
        chat_id = str(msg.get("chat", {}).get("id", ""))
        chat_type = msg.get("chat", {}).get("type", "")
        if chat_id != str(TELEGRAM_CHAT_ID) or chat_type != "private":
            logger.warning(f"Ignored message from unknown chat: {chat_id}")
            return

        text = msg.get("text", "").strip().lower()
        if not text:
            return

        logger.info(f"Received command: {text}")
        self._route_command(text)

    def _handle_callback(self, callback: dict):
        msg = callback.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        chat_type = msg.get("chat", {}).get("type", "")
        if chat_id != str(TELEGRAM_CHAT_ID) or chat_type != "private":
            logger.warning(f"Ignored callback from unknown chat: {chat_id}")
            return

        data = callback.get("data", "")
        query_id = callback.get("id")
        if not data or not query_id:
            return

        logger.info(f"Received callback: {data}")
        if data == "buy:BNB":
            handled = self._cmd_buy_button()
        elif data == "sell:BNB":
            handled = self._cmd_sell_button()
        elif data == "skip:BNB":
            handled = self._cmd_skip_button()
        elif data in {"test:buy", "test:sell", "test:skip"}:
            handled = True
        else:
            handled = False

        if data.startswith("test:"):
            message = "Buttons are working."
        else:
            message = "Action recorded." if handled else "No pending action for that button."
        self.notifier.answer_callback(query_id, message)

    # ── Command router ───────────────────────────────────────

    def _route_command(self, text: str):
        parts = text.split()
        cmd   = parts[0] if parts else ""

        if cmd == "bought":
            self._cmd_bought(parts)
        elif cmd == "sold":
            self._cmd_sold(parts)
        elif cmd == "skip":
            self._cmd_skip()
        elif cmd == "status":
            self._cmd_status()
        elif cmd == "buttons":
            self._cmd_buttons()
        elif cmd == "reset":
            self._cmd_reset()
        elif cmd == "pause":
            self._cmd_pause(parts)
        elif cmd == "resume":
            self._cmd_resume()
        elif cmd in ("help", "/help", "/start"):
            self._cmd_help()
        else:
            safe_text = html.escape(text, quote=False)
            self.notifier.send(
                f"🤔 I didn't understand <code>{safe_text}</code>\n"
                f"Send <b>help</b> to see all commands."
            )

    # ── Commands ─────────────────────────────────────────────

    def _parse_positive_number(self, raw_value: str, field_name: str, *, minimum: float = 0.0, maximum: float = None):
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            self.notifier.send(f"Invalid {field_name}.")
            return None

        if not math.isfinite(value) or value <= minimum:
            self.notifier.send(f"{field_name.capitalize()} must be greater than {minimum}.")
            return None

        if maximum is not None and value > maximum:
            self.notifier.send(f"{field_name.capitalize()} must be at most {maximum:,.2f}.")
            return None

        return value

    def _cmd_bought(self, parts: list):
        """
        bought <price>            → confirm buy at that price, use suggested USDT amount
        bought <price> <amount>   → confirm buy at that price with custom USDT amount
        """
        if len(parts) < 2:
            self.notifier.send("Usage: <code>bought 617.20</code> or <code>bought 617.20 45</code>")
            return

        actual_price = self._parse_positive_number(parts[1], "price", maximum=1_000_000)
        if actual_price is None:
            self.notifier.send("Example: <code>bought 617.20</code>")
            return

        coin       = "BNB"
        cs         = self.state.get(coin)
        total_fund = cs.get("total_fund", 500)
        tranche_lvl = cs.get("tranche_level", 0)
        deployed = cs.get("deployed_usdt", 0)
        from config import TRANCHE_LEVELS, MAX_DEPLOY_PCT
        remaining = max(0.0, total_fund * (MAX_DEPLOY_PCT / 100) - deployed)

        if remaining < 5:
            self.notifier.send("No deployable balance remains within the configured risk cap.")
            return

        # Use custom amount if provided, else use tranche schedule
        if len(parts) >= 3:
            usdt_amount = self._parse_positive_number(parts[2], "amount", maximum=remaining)
            if usdt_amount is None:
                self.notifier.send("Example: <code>bought 617.20 45</code>")
                return
        else:
            # Calculate tranche amount from schedule
            if tranche_lvl < len(TRANCHE_LEVELS):
                usdt_amount = total_fund * (TRANCHE_LEVELS[tranche_lvl]["deploy_pct"] / 100)
            else:
                usdt_amount = total_fund * 0.05  # fallback 5%
            # Cap at remaining capacity
            usdt_amount = min(usdt_amount, remaining)

        if usdt_amount < 5:
            self.notifier.send("Amount must be at least 5 USDT.")
            return

        # Record the buy in state
        self.state.record_buy_alert(coin, actual_price, usdt_amount)

        # Get updated state to show new targets
        updated    = self.state.get(coin)
        new_avg    = updated.get("avg_cost", actual_price)
        deployed   = updated.get("deployed_usdt", usdt_amount)
        from config import TAKE_PROFIT_PCT, FEE_BUFFER_PCT
        sell_target = new_avg * (1 + (TAKE_PROFIT_PCT + FEE_BUFFER_PCT) / 100)
        net_target  = new_avg * (1 + TAKE_PROFIT_PCT / 100)

        msg = f"""
✅ <b>Buy confirmed — BNB</b>
━━━━━━━━━━━━━━━━━━━━
💰 Bought: <b>${usdt_amount:,.2f} USDT</b> at <b>${actual_price:,.2f}</b>
🪙 ~{usdt_amount/actual_price:.6f} BNB

📊 Updated position:
   • Avg cost:    <b>${new_avg:,.2f}</b>
   • Deployed:    <b>${deployed:,.2f}</b> / ${total_fund:,}
   • Sell target: <b>${sell_target:,.2f}</b>
     (net profit target: ${net_target:,.2f})

⏳ Watching for {TAKE_PROFIT_PCT}% recovery...
<i>I'll alert you when price hits ${sell_target:,.2f}</i>
"""
        self.notifier.send(msg.strip())

    def _cmd_sold(self, parts: list):
        """
        sold <price>  → confirm sell at actual price, calculates real P&L
        """
        if len(parts) < 2:
            self.notifier.send("Usage: <code>sold 639.50</code>")
            return

        actual_price = self._parse_positive_number(parts[1], "price", maximum=1_000_000)
        if actual_price is None:
            self.notifier.send("Example: <code>sold 639.50</code>")
            return

        coin = "BNB"
        cs   = self.state.get(coin)
        avg  = cs.get("avg_cost")
        dep  = cs.get("deployed_usdt", 0)

        if not avg or dep == 0:
            self.notifier.send("⚠️ No open position to close. Start by buying first.")
            return

        from config import FEE_BUFFER_PCT
        gross_pct   = (actual_price - avg) / avg * 100
        net_pct     = gross_pct - FEE_BUFFER_PCT
        usdt_return = dep * (actual_price / avg)
        net_gain    = usdt_return - dep

        # Record sell and reset
        self.state.record_sell_alert(coin, actual_price)

        icon = "🟢" if net_gain >= 0 else "🔴"

        msg = f"""
{icon} <b>Sell confirmed — BNB</b>
━━━━━━━━━━━━━━━━━━━━
💲 Sold at: <b>${actual_price:,.2f}</b>
📌 Avg cost was: <b>${avg:,.2f}</b>

📊 Final P&L:
   • Deployed:   ${dep:,.2f} USDT
   • Return:     ${usdt_return:,.2f} USDT
   • Gross:      {gross_pct:+.2f}%
   • Est. fees:  −{FEE_BUFFER_PCT}%
   • Net profit: <b>${net_gain:+,.2f} ({net_pct:+.2f}%)</b>

🔄 Position reset. Baseline set to ${actual_price:,.2f}
⏳ Watching for next dip...
"""
        self.notifier.send(msg.strip())

    def _cmd_buy_button(self) -> bool:
        pending = self.state.get("BNB").get("pending_action") or {}
        if pending.get("type") != "BUY":
            return False

        self.state.record_buy_alert("BNB", pending["price"], pending["usdt_amount"])
        self._send_buy_confirmation(pending["price"], pending["usdt_amount"])
        return True

    def _cmd_sell_button(self) -> bool:
        pending = self.state.get("BNB").get("pending_action") or {}
        if pending.get("type") != "SELL":
            return False

        self._finalize_sell("BNB", pending["price"])
        return True

    def _cmd_skip_button(self) -> bool:
        pending = self.state.get("BNB").get("pending_action") or {}
        if pending.get("type") != "BUY":
            return False

        self.state.set_baseline("BNB", pending["price"])
        self.state.set_pending_action("BNB", None)
        self.notifier.send(
            f"⏭ <b>Signal skipped.</b>\n"
            f"Baseline updated to current price: <b>${pending['price']:,.2f}</b>\n"
            f"Watching for next −2% dip from here."
        )
        return True

    def _send_buy_confirmation(self, actual_price: float, usdt_amount: float):
        coin = "BNB"
        updated = self.state.get(coin)
        total_fund = updated.get("total_fund", 500)
        new_avg = updated.get("avg_cost", actual_price)
        deployed = updated.get("deployed_usdt", usdt_amount)
        from config import TAKE_PROFIT_PCT, FEE_BUFFER_PCT
        sell_target = new_avg * (1 + (TAKE_PROFIT_PCT + FEE_BUFFER_PCT) / 100)
        net_target = new_avg * (1 + TAKE_PROFIT_PCT / 100)

        msg = f"""
✅ <b>Buy confirmed — BNB</b>
━━━━━━━━━━━━━━━━━━━━
💰 Bought: <b>${usdt_amount:,.2f} USDT</b> at <b>${actual_price:,.2f}</b>
🪙 ~{usdt_amount/actual_price:.6f} BNB

📊 Updated position:
   • Avg cost:    <b>${new_avg:,.2f}</b>
   • Deployed:    <b>${deployed:,.2f}</b> / ${total_fund:,}
   • Sell target: <b>${sell_target:,.2f}</b>
     (net profit target: ${net_target:,.2f})

⏳ Watching for {TAKE_PROFIT_PCT}% recovery...
<i>I'll alert you when price hits ${sell_target:,.2f}</i>
"""
        self.notifier.send(msg.strip())

    def _finalize_sell(self, coin: str, actual_price: float):
        cs = self.state.get(coin)
        avg = cs.get("avg_cost")
        dep = cs.get("deployed_usdt", 0)
        if not avg or dep == 0:
            self.notifier.send("⚠️ No open position to close. Start by buying first.")
            return

        from config import FEE_BUFFER_PCT
        gross_pct = (actual_price - avg) / avg * 100
        net_pct = gross_pct - FEE_BUFFER_PCT
        usdt_return = dep * (actual_price / avg)
        net_gain = usdt_return - dep

        self.state.record_sell_alert(coin, actual_price)

        icon = "🟢" if net_gain >= 0 else "🔴"
        msg = f"""
{icon} <b>Sell confirmed — BNB</b>
━━━━━━━━━━━━━━━━━━━━
💲 Sold at: <b>${actual_price:,.2f}</b>
📌 Avg cost was: <b>${avg:,.2f}</b>

📊 Final P&L:
   • Deployed:   ${dep:,.2f} USDT
   • Return:     ${usdt_return:,.2f} USDT
   • Gross:      {gross_pct:+.2f}%
   • Est. fees:  −{FEE_BUFFER_PCT}%
   • Net profit: <b>${net_gain:+,.2f} ({net_pct:+.2f}%)</b>

🔄 Position reset. Baseline set to ${actual_price:,.2f}
⏳ Watching for next dip...
"""
        self.notifier.send(msg.strip())

    def _cmd_skip(self):
        """Skip the last signal — update baseline to current price without buying."""
        from price_feed import get_prices
        prices = get_prices(["BNB"])
        price  = prices.get("BNB")

        if price:
            self.state.set_baseline("BNB", price)
            self.state.set_pending_action("BNB", None)
            self.notifier.send(
                f"⏭ <b>Signal skipped.</b>\n"
                f"Baseline updated to current price: <b>${price:,.2f}</b>\n"
                f"Watching for next −2% dip from here."
            )
        else:
            self.notifier.send("⚠️ Couldn't fetch current price. Try again.")

    def _cmd_status(self):
        """Send current position status."""
        from price_feed import get_prices
        from config import TAKE_PROFIT_PCT, FEE_BUFFER_PCT, TRANCHE_LEVELS
        prices = get_prices(["BNB"])
        price  = prices.get("BNB", 0)
        cs     = self.state.get("BNB")

        dep      = cs.get("deployed_usdt", 0)
        avg      = cs.get("avg_cost")
        units    = cs.get("position_size", 0)
        baseline = cs.get("baseline_price", price)
        tranche  = cs.get("tranche_level", 0)
        fund     = cs.get("total_fund", 500)

        if dep > 0 and avg:
            cur_val     = units * price
            pnl_usd     = cur_val - dep
            pnl_pct     = (price - avg) / avg * 100
            sell_target = avg * (1 + (TAKE_PROFIT_PCT + FEE_BUFFER_PCT) / 100)
            gap         = ((sell_target - price) / price * 100)
            icon        = "🟢" if pnl_pct >= 0 else "🔴"

            msg = f"""
📊 <b>BNB Status — Open Position</b>
━━━━━━━━━━━━━━━━━━━━
🔶 Current price: <b>${price:,.2f}</b>
📌 Avg cost:      <b>${avg:,.2f}</b>
🎯 Sell target:   <b>${sell_target:,.2f}</b> (need +{gap:.1f}% more)

{icon} Unrealised: <b>${pnl_usd:+,.2f} ({pnl_pct:+.2f}%)</b>

💼 Position:
   • {units:.6f} BNB held
   • ${dep:,.2f} deployed ({dep/fund*100:.0f}% of fund)
   • Tranche level: {tranche}/5

💰 Remaining: ${fund*(1-dep/fund):,.0f} USDT ready
"""
        else:
            drop = (baseline - price) / baseline * 100 if baseline else 0
            next_trigger = 2.0
            for i, lvl in enumerate(TRANCHE_LEVELS):
                if tranche <= i:
                    next_trigger = lvl["dip_pct"]
                    break
            gap = next_trigger - drop

            msg = f"""
📊 <b>BNB Status — Watching</b>
━━━━━━━━━━━━━━━━━━━━
🔶 Current price: <b>${price:,.2f}</b>
📌 Baseline:      <b>${baseline:,.2f}</b>
📉 Drop so far:   <b>{drop:.2f}%</b>
⏳ Need {gap:.2f}% more to trigger L1

💰 Ready to deploy: <b>${fund*0.75:,.0f} USDT</b>
🔍 Watching every 45 seconds...
"""
        self.notifier.send(msg.strip())

    def _cmd_buttons(self):
        """Send test inline buttons so the chat UI can be verified."""
        self.notifier.send_button_test()

    def _cmd_reset(self):
        """Reset BNB state completely."""
        from price_feed import get_prices
        prices = get_prices(["BNB"])
        price  = prices.get("BNB", 0)
        self.state.reset_coin("BNB", price)
        self.notifier.send(
            f"🔄 <b>BNB state fully reset.</b>\n"
            f"Baseline set to current price: <b>${price:,.2f}</b>\n"
            f"All positions and tranches cleared."
        )

    def _cmd_pause(self, parts: list):
        """Pause alerts for N hours (default 2)."""
        hours = 2
        if len(parts) >= 2:
            try:
                hours = int(parts[1])
            except ValueError:
                pass
        hours = max(1, min(hours, 24))
        self.paused_until = datetime.utcnow() + timedelta(hours=hours)
        self.notifier.send(
            f"⏸ <b>Alerts paused for {hours} hour(s).</b>\n"
            f"Resuming at {self.paused_until.strftime('%H:%M UTC')}.\n"
            f"Send <b>resume</b> to unpause early."
        )

    def _cmd_resume(self):
        """Resume alerts immediately."""
        self.paused_until = None
        self.notifier.send("▶️ <b>Alerts resumed.</b> Watching BNB again.")

    def _cmd_help(self):
        msg = """
🤖 <b>BNB Bot Commands</b>
━━━━━━━━━━━━━━━━━━━━

<b>After a BUY alert:</b>
<code>bought 617.20</code>      — confirm buy at this price
<code>bought 617.20 45</code>   — confirm buy, custom USDT amount
<code>skip</code>               — skip signal, reset baseline

<b>After a SELL alert:</b>
<code>sold 639.50</code>        — confirm sell, see real P&L

<b>Anytime:</b>
<code>status</code>             — current position + targets
<code>buttons</code>            — send test inline buttons
<code>pause</code>              — pause alerts 2 hrs
<code>pause 4</code>            — pause for 4 hrs
<code>resume</code>             — unpause now
<code>reset</code>              — clear all state, start fresh
<code>help</code>               — this message

<b>Buttons:</b>
Tap <code>Buy</code>, <code>Sell</code>, or <code>Skip</code> on alerts.
If you do nothing, the bot takes no action.
"""
        self.notifier.send(msg.strip())
