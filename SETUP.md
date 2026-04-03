# 🤖 Crypto Notification Bot — Setup Guide

A 24/7 market watcher that pings your Telegram when it's time to **buy a dip** or **take profit**. You stay in control — it just handles the watching.

---

## What You'll Need

- A phone with Telegram installed
- Python 3.8+ on your computer or a VPS
- A free Binance account (just for price reference — no API key needed for this bot)
- 10 minutes to set up

---

## Step 1 — Create Your Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Give it a name (e.g. `MyCryptoWatcher`) and a username (e.g. `mycryptowatcher_bot`)
4. BotFather will give you a **token** like: `7213456789:AAGxxx...` → copy this

**Get your Chat ID:**
1. Search for **@userinfobot** on Telegram
2. Send `/start` — it replies with your numeric chat ID (e.g. `912345678`)

---

## Step 2 — Configure the Bot

Copy `config.example.py` to `config.py`, then fill in your own values:

```bash
cp config.example.py config.py
```

Open `config.py` and fill in:

```python
TELEGRAM_BOT_TOKEN = "7213456789:AAGxxx..."   # from BotFather
TELEGRAM_CHAT_ID   = "912345678"              # from userinfobot
```

Then set your fund sizes (how much USDT per coin you're willing to deploy):

```python
FUND_PER_COIN = {
    "BTC": 500,   # $500 max into BTC
    "ETH": 500,   # $500 max into ETH
    "SOL": 300,
    "BNB": 200,
}
```

Adjust the strategy thresholds if you want (defaults are conservative):

```python
DIP_TRIGGER_PCT  = 3.0   # alert when coin drops 3% from baseline
TAKE_PROFIT_PCT  = 4.0   # alert when coin is 4% above your avg cost
```

---

## Step 3 — Install & Run

```bash
# Install Python dependency (just one)
pip install requests

# Run the bot
python3 main.py
```

You should immediately get a Telegram message like:
> 🤖 Crypto Watcher Bot Started
> ₿ BTC: $67,234.00 | Ξ ETH: $3,521.00 | ...

---

## Step 4 — Run It 24/7 (Important)

The bot needs to run continuously. Options:

### Option A — Keep it running on your PC (simple)
```bash
# On Mac/Linux, use nohup so it keeps running after you close terminal
nohup python main.py &

# To stop it
kill $(pgrep -f main.py)
```

### Option B — VPS (recommended for reliability)
A VPS from [Hetzner](https://hetzner.com) or [DigitalOcean](https://digitalocean.com) costs ~₹400-500/month.

```bash
# On the VPS, use systemd or screen
screen -S cryptobot
python main.py
# Press Ctrl+A then D to detach
```

### Option C — Run as a systemd service (Linux, most reliable)
```ini
# /etc/systemd/system/cryptobot.service
[Unit]
Description=Crypto Notification Bot
After=network.target

[Service]
WorkingDirectory=/home/youruser/crypto_bot
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable cryptobot
sudo systemctl start cryptobot
```

---

## How the Bot Thinks

```
Initial state: baseline = current price, all funds in USDT

Every 60 seconds:
  └─ Fetch prices from Binance
  └─ For each coin:
       └─ Price dropped 3%+ from baseline?
            └─ YES → 📱 "BUY Tranche 1: put $50 into ETH"
                      Update baseline to new low
       └─ Price > avg cost + 4.2% (profit + fees)?
            └─ YES → 📱 "TAKE PROFIT: sell ETH → +$18.40"
                      Reset state, new baseline = current price
       └─ Neither → HOLD silently
```

---

## Example Notification — BUY

```
🟢 BUY ALERT — Ξ ETH/USDT
━━━━━━━━━━━━━━━━━━━━━━
📉 Price dropped 3.4% from baseline
💰 Current Price: $3,380.00
📌 Baseline was: $3,502.00

🎯 ACTION: Buy Tranche 1
🔴⚪⚪⚪⚪

💵 Suggested amount: $50 USDT
🪙 You'll get ~0.014793 ETH

📊 After this trade:
   • Avg cost: $3,380.00
   • Deployed: $50 / $500
   • Remaining: $450 USDT
```

**You then manually go to your exchange and buy $50 of ETH.**

---

## Example Notification — SELL

```
💰 TAKE PROFIT ALERT — Ξ ETH/USDT
━━━━━━━━━━━━━━━━━━━━━━
📈 Price is 4.5% above your avg cost!

💲 Current Price:  $3,641.00
📌 Your Avg Cost:  $3,485.20
🎯 Target was:     $3,555.00

🎯 ACTION: Sell ALL ETH → USDT

📊 Estimated P&L:
   • Deployed:    $175 USDT
   • Return:      $182.73 USDT
   • Net Profit:  +$7.73 (4.3%)
```

**You manually sell, and confirm. The bot resets baseline to current price.**

---

## Strategy Parameters Explained

| Parameter | What it does | Conservative | Aggressive |
|---|---|---|---|
| `DIP_TRIGGER_PCT` | How much must price fall to trigger a buy alert | 4–5% | 2–3% |
| `TAKE_PROFIT_PCT` | How much must price rise above avg cost to take profit | 5–6% | 3–4% |
| `FEE_BUFFER_PCT` | Estimated exchange round-trip fee | 0.2% | 0.1% |
| `MAX_DEPLOY_PCT` | Max % of your fund to deploy into one coin | 70% | 85% |
| `ALERT_COOLDOWN_MIN` | Minutes before re-alerting on same coin | 60 | 20 |

---

## Tranche Level Logic

Each dip level allocates a bigger chunk of your fund:

| Level | Dip from baseline | Deploy |
|---|---|---|
| 1 | −3% | 10% of fund |
| 2 | −6% | 15% of fund |
| 3 | −10% | 20% of fund |
| 4 | −15% | 25% of fund |
| 5 | −22% | 10% (last reserve) |

**Maximum exposure:** 80% of your fund. 20% always stays as USDT.

---

## Files Overview

```
crypto_bot/
├── main.py          ← Run this
├── config.py        ← Edit your settings here
├── strategy.py      ← DCA grid logic (don't need to edit)
├── state.py         ← Saves coin positions to disk
├── price_feed.py    ← Fetches prices from Binance (no key needed)
├── notifier.py      ← Sends Telegram messages
├── requirements.txt ← Just: requests
├── bot_state.json   ← Auto-created: tracks your positions
└── bot_trades.log   ← Auto-created: full trade alert history
```

---

## Risks & Limitations

- **Death spiral risk:** If a coin drops 80% over months, your tranches deplete. The 80% MAX_DEPLOY cap protects you, but pick solid coins (BTC, ETH).
- **This does NOT trade for you.** It notifies. You execute. You're always in control.
- **Always verify price on your exchange** before executing — Binance prices are reference only.
- **Tax:** In India, every crypto-to-crypto or crypto-to-stable swap is a taxable event. Keep the `bot_trades.log` for your records.

---

## Questions?

Check `bot_trades.log` for a full history of all alerts.
Check `bot_state.json` to see current state of each coin.
