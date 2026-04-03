"""
notifier.py — Telegram alerts, BNB-specific version
Rich messages with price zone context, sell target, and fee breakdown
"""
import html
import requests
import logging
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BNB_CONTEXT

logger = logging.getLogger(__name__)


class TelegramNotifier:

    def __init__(self):
        self.url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        self.chat_id = TELEGRAM_CHAT_ID

    def send(self, message: str, reply_markup: dict | None = None) -> bool:
        payload = {
            "chat_id":    self.chat_id,
            "text":       message,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            r = requests.post(self.url, json=payload, timeout=10)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False

    def answer_callback(self, callback_query_id: str, text: str) -> bool:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text},
                timeout=10,
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram callback error: {e}")
            return False

    def send_buy_alert(self, coin: str, ctx: dict) -> bool:
        now   = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
        lvl   = ctx["tranche_level"]
        bars  = "🔴" * lvl + "⚪" * (5 - lvl)
        price = ctx["current_price"]

        # Support zone indicator
        if ctx.get("near_support"):
            zone_line = f"📍 Zone: <b>{ctx['price_zone']}</b> ← near $600 floor!"
        else:
            zone_line = f"📍 Zone: <b>{ctx['price_zone']}</b>"

        msg = f"""
🟢 <b>BNB BUY ALERT — Tranche {lvl}</b>
━━━━━━━━━━━━━━━━━━━━━━
{ctx.get('urgency', '📊 Standard dip')}
{zone_line}

📉 Dropped <b>{ctx['drop_pct']}%</b> from baseline
💰 Current price: <b>${price:,.2f}</b>
📌 Baseline was: <b>${ctx['baseline_price']:,.2f}</b>

{bars}

💵 Buy: <b>${ctx['tranche_usdt']:,} USDT</b>
🪙 You get: ~<b>{ctx['coin_units']} BNB</b>

📊 After this trade:
   • New avg cost: <b>${ctx['avg_cost_after']:,.2f}</b>
   • Sell target:  <b>${ctx['sell_target']:,.2f}</b> (+{ctx.get('take_profit_pct', 3.5)+ctx.get('fee_pct', 0.25):.2f}%)
   • Deployed: <b>${ctx['deployed_usdt'] + ctx['tranche_usdt']:,.0f}</b> / ${ctx['total_fund']:,} ({ctx['deploy_pct_after']}%)
   • Remaining USDT: <b>${ctx['remaining_usdt']:,.0f}</b>

📈 2026 range: $580–$900 (avg $740)
⏰ {now}
━━━━━━━━━━━━━━━━━━━━━━
<i>Execute manually on Binance. Bot tracks your avg cost.</i>
"""
        buttons = {
            "inline_keyboard": [[
                {"text": "Buy", "callback_data": f"buy:{coin}"},
                {"text": "Skip", "callback_data": f"skip:{coin}"},
            ]]
        }
        return self.send(msg.strip(), reply_markup=buttons)

    def send_sell_alert(self, coin: str, ctx: dict) -> bool:
        now = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")

        msg = f"""
💰 <b>BNB TAKE PROFIT ALERT</b>
━━━━━━━━━━━━━━━━━━━━━━
📈 Price is <b>{ctx['gross_profit_pct']}%</b> above your avg cost!
📍 Zone: <b>{ctx.get('price_zone', 'n/a')}</b>

💲 Current price:  <b>${ctx['current_price']:,.2f}</b>
📌 Your avg cost:  <b>${ctx['avg_cost']:,.2f}</b>
🎯 Target was:     <b>${ctx['take_profit_at']:,.2f}</b>

🎯 <b>ACTION: Sell ALL BNB → USDT</b>

📊 P&L breakdown:
   • Deployed:      <b>${ctx['deployed_usdt']:,} USDT</b>
   • Return:        <b>${ctx['usdt_return']:,.2f} USDT</b>
   • Gross profit:  +{ctx['gross_profit_pct']}%
   • Est. fees:     −{ctx['fee_pct']}%
   • Net profit:    <b>+${ctx['net_gain_usdt']:,.2f} ({ctx['net_profit_pct']}%)</b>

✅ After selling → baseline resets to ${ctx['current_price']:,.2f}
🔄 Bot enters watch mode for next dip

⏰ {now}
━━━━━━━━━━━━━━━━━━━━━━
<i>Sell on Binance spot, then confirm to reset bot state.</i>
"""
        buttons = {
            "inline_keyboard": [[
                {"text": "Sell", "callback_data": f"sell:{coin}"},
            ]]
        }
        return self.send(msg.strip(), reply_markup=buttons)

    def send_button_test(self) -> bool:
        buttons = {
            "inline_keyboard": [[
                {"text": "Buy", "callback_data": "test:buy"},
                {"text": "Sell", "callback_data": "test:sell"},
                {"text": "Skip", "callback_data": "test:skip"},
            ]]
        }
        msg = (
            "🧪 <b>Button test</b>\n"
            "Tap any button below to confirm inline buttons are working.\n"
            "These test buttons do not change bot state."
        )
        return self.send(msg, reply_markup=buttons)

    def send_startup_message(self, coins: list, prices: dict) -> bool:
        now   = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
        price = prices.get("BNB", 0)
        ctx   = BNB_CONTEXT

        # Determine starting zone
        if price <= ctx["support_strong"]:
            zone_note = "at key support — excellent entry zone"
        elif price <= 640:
            zone_note = "near support — decent entry zone"
        elif price <= ctx["resistance"]:
            zone_note = "mid-range — watching for dip"
        else:
            zone_note = "above resistance — waiting for pullback"

        msg = f"""
🤖 <b>BNB Watcher Bot Started</b>
━━━━━━━━━━━━━━━━━━━━━━
🔶 BNB/USDT: <b>${price:,.2f}</b>
📍 {zone_note}

📊 Market context:
   • Support:    $600 (strong floor)
   • Resistance: $680
   • 2026 range: $580 – $900
   • Daily vol:  ~2.65%

⚙️ Strategy calibrated:
   • Dip trigger: 2% drop from baseline
   • Take profit: 3.5% above avg cost
   • Max deploy:  75% of fund
   • Check every: 45 seconds

⏰ Started: {now}
━━━━━━━━━━━━━━━━━━━━━━
<i>I'll ping you when it's time to act. Sit back 😎</i>
"""
        return self.send(msg.strip())

    def send_daily_summary(self, coins: list, prices: dict, states: dict) -> bool:
        now   = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
        price = prices.get("BNB", 0)
        s     = states.get("BNB", {})
        dep   = s.get("deployed_usdt", 0)
        avg   = s.get("avg_cost")
        units = s.get("position_size", 0)
        fund  = s.get("total_fund", 500)
        tranche = s.get("tranche_level", 0)

        cur_val  = units * price if units and price else 0
        pnl_pct  = ((price - avg) / avg * 100) if avg and price else 0
        pnl_usd  = cur_val - dep if dep > 0 else 0
        pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"

        if dep > 0 and avg:
            sell_target = avg * (1 + 3.75 / 100)
            gap_to_sell = ((sell_target - price) / price * 100)
            position_block = f"""
💼 Position:
   • Holdings: {units:.6f} BNB
   • Avg cost: ${avg:,.2f}
   • Sell target: ${sell_target:,.2f} (need +{gap_to_sell:.1f}% more)
   • Deployed: ${dep:,.2f} ({dep/fund*100:.0f}% of fund)
   • {pnl_icon} Unrealised: ${pnl_usd:+,.2f} ({pnl_pct:+.2f}%)
   • Tranche level: {tranche}/5"""
        else:
            baseline = s.get("baseline_price", price)
            drop_needed = (baseline - price) / baseline * 100 if baseline else 0
            position_block = f"""
💼 Position: <b>WATCHING</b> (no BNB held)
   • Baseline: ${baseline:,.2f}
   • Current: ${price:,.2f}
   • Drop so far: {drop_needed:.2f}% (need 2% to trigger L1)
   • Ready to deploy: ${fund * 0.75:,.0f} USDT"""

        msg = f"""
📊 <b>BNB Daily Summary</b>
━━━━━━━━━━━━━━━━━━━━━━
🔶 BNB: <b>${price:,.2f}</b>
{position_block}

📈 Context:
   • Support: $600 | Resistance: $680
   • Daily volatility: ~2.65%

⏰ {now}
"""
        return self.send(msg.strip())

    def send_error_alert(self, error_msg: str):
        safe_error = html.escape(error_msg[:300], quote=False)
        self.send(f"⚠️ <b>Bot Error</b>\n<code>{safe_error}</code>")
