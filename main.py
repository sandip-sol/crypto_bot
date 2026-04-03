"""
main.py — BNB Notification Bot with two-way Telegram chat
Run: python3 main.py
"""
import time
import logging
import signal
import sys
from datetime import datetime, timedelta

from config import COINS, POLL_INTERVAL_SEC, LOG_FILE
from price_feed import get_prices
from strategy import StrategyEngine, Signal
from state import StateManager
from notifier import TelegramNotifier
from telegram_handler import TelegramHandler

# ── Logging setup ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


class CryptoBot:
    def __init__(self):
        self.state    = StateManager()
        self.strategy = StrategyEngine()
        self.notifier = TelegramNotifier()
        self.handler  = TelegramHandler(self.state, self.notifier)
        self.running  = True
        self.last_daily_summary = None

        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, *_):
        logger.info("Shutting down...")
        self.handler.stop()
        self.running = False

    def run(self):
        logger.info("=" * 50)
        logger.info("  BNB Notification Bot Starting")
        logger.info("=" * 50)

        prices = get_prices(COINS)
        for coin in COINS:
            cs = self.state.get(coin)
            if cs["baseline_price"] is None and prices.get(coin):
                self.state.reset_coin(coin, prices[coin])
                logger.info(f"{coin} baseline: ${prices[coin]:,.2f}")

        self.handler.start()
        self.notifier.send_startup_message(COINS, prices)

        while self.running:
            try:
                if not self.handler.is_paused():
                    self._tick()
                else:
                    logger.debug("Bot paused — skipping tick")
                self._maybe_daily_summary()
            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)
                self.notifier.send_error_alert(str(e))
            time.sleep(POLL_INTERVAL_SEC)

        logger.info("Bot stopped.")

    def _tick(self):
        prices = get_prices(COINS)
        for coin in COINS:
            price = prices.get(coin)
            if not price:
                continue
            state  = self.state.get(coin)
            sig, ctx = self.strategy.evaluate(coin, price, state)

            if sig == Signal.BUY:
                logger.info(f"BUY {coin} @ ${price:,.2f}")
                self.state.set_pending_action(coin, {
                    "type": "BUY",
                    "price": ctx["current_price"],
                    "usdt_amount": ctx["tranche_usdt"],
                    "created_at": datetime.utcnow().isoformat(),
                })
                self.notifier.send_buy_alert(coin, ctx)
                self.state.update(coin, {
                    "last_alert_time": datetime.utcnow().isoformat(),
                    "last_alert_type": "BUY_PENDING",
                })
            elif sig == Signal.SELL:
                logger.info(f"SELL {coin} @ ${price:,.2f}")
                self.state.set_pending_action(coin, {
                    "type": "SELL",
                    "price": ctx["current_price"],
                    "created_at": datetime.utcnow().isoformat(),
                })
                self.notifier.send_sell_alert(coin, ctx)
                self.state.update(coin, {
                    "last_alert_time": datetime.utcnow().isoformat(),
                    "last_alert_type": "SELL_PENDING",
                })
            else:
                logger.debug(f"HOLD {coin} @ ${price:,.2f} | {ctx.get('reason','')}")

    def _maybe_daily_summary(self):
        now = datetime.utcnow()
        if now.hour == 8 and now.minute < 1:
            if not self.last_daily_summary or \
               (now - self.last_daily_summary) > timedelta(hours=23):
                prices = get_prices(COINS)
                self.notifier.send_daily_summary(COINS, prices, self.state.all_coins())
                self.last_daily_summary = now
                logger.info("Daily summary sent.")


if __name__ == "__main__":
    bot = CryptoBot()
    bot.run()
