# Crypto Bot

A Telegram-based crypto notification bot that watches the BNB/USDT market and alerts you when it may be a good time to buy a dip or take profit.

This bot does not place trades automatically. It watches the market, tracks your local trading state, and sends action prompts to Telegram so you can decide what to do manually.

## Features

- Watches `BNB` price movement using market data
- Sends Telegram buy and sell alerts
- Tracks deployed capital, average cost, and pending actions
- Includes multi-level tranche buying logic
- Supports a daily summary and bot pause/resume flow
- Keeps runtime state and logs local to your machine

## Project Files

- `main.py`: bot entrypoint and main loop
- `strategy.py`: dip-buy and take-profit decision logic
- `state.py`: local state management
- `notifier.py`: Telegram alert formatting and delivery
- `telegram_handler.py`: Telegram command handling
- `price_feed.py`: market price fetching
- `config.example.py`: safe config template for new setups
- `SETUP.md`: detailed setup guide

## Quick Start

1. Create your local config:

```bash
cp config.example.py config.py
```

2. Edit `config.py` and add:

- your Telegram bot token
- your Telegram chat ID
- your preferred fund size and strategy values

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run the bot:

```bash
python3 main.py
```

## Notes

- `config.py` is intentionally ignored by git so secrets do not get committed.
- `bot_state.json` and `bot_trades.log` are local runtime files and are also ignored.
- This repository is currently configured around `BNB` only.

## Setup Guide

For the full walkthrough, examples, and deployment options, see [SETUP.md](./SETUP.md).
