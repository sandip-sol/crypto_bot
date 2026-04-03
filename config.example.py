# Copy this file to config.py and fill in your own Telegram details.

# Telegram
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

# Single coin: BNB only
COINS = ["BNB"]

# Your total USDT fund allocated to BNB
FUND_PER_COIN = {
    "BNB": 500,
}

# Strategy parameters
DIP_TRIGGER_PCT = 2.0
TAKE_PROFIT_PCT = 3.5
FEE_BUFFER_PCT = 0.25
MAX_DEPLOY_PCT = 75.0

TRANCHE_LEVELS = [
    {"dip_pct": 2.0, "deploy_pct": 8},
    {"dip_pct": 4.0, "deploy_pct": 12},
    {"dip_pct": 7.0, "deploy_pct": 18},
    {"dip_pct": 11.0, "deploy_pct": 22},
    {"dip_pct": 16.0, "deploy_pct": 15},
]

POLL_INTERVAL_SEC = 45
ALERT_COOLDOWN_MIN = 20
MIN_NET_PROFIT_PCT = TAKE_PROFIT_PCT + FEE_BUFFER_PCT

STATE_FILE = "bot_state.json"
LOG_FILE = "bot_trades.log"
