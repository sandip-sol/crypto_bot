"""
price_feed.py — Fetches live prices from Binance public REST API
No API key required for public price data.
"""
import requests
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_24H_URL    = "https://api.binance.com/api/v3/ticker/24hr"


def get_prices(coins: list) -> Dict[str, Optional[float]]:
    """
    Fetch current prices for a list of coins (vs USDT) from Binance.
    Returns: {"BTC": 67234.5, "ETH": 3521.2, ...}
    """
    symbols = [f"{coin}USDT" for coin in coins]
    prices  = {}

    try:
        # Batch request for all symbols
        params   = {"symbols": str(symbols).replace("'", '"').replace(" ", "")}
        response = requests.get(BINANCE_TICKER_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        for item in data:
            symbol = item["symbol"]
            coin   = symbol.replace("USDT", "")
            if coin in coins:
                prices[coin] = float(item["price"])

    except requests.RequestException as e:
        logger.error(f"Price fetch error: {e}")
        # Fallback: fetch one by one
        for coin in coins:
            try:
                r = requests.get(
                    BINANCE_TICKER_URL,
                    params={"symbol": f"{coin}USDT"},
                    timeout=10
                )
                r.raise_for_status()
                prices[coin] = float(r.json()["price"])
            except Exception as err:
                logger.error(f"Failed to fetch {coin}: {err}")
                prices[coin] = None

    return prices


def get_24h_stats(coins: list) -> Dict[str, dict]:
    """
    Fetch 24h stats: price change %, high, low, volume.
    Useful for context in notifications.
    """
    stats = {}
    try:
        symbols = [f"{coin}USDT" for coin in coins]
        params  = {"symbols": str(symbols).replace("'", '"').replace(" ", "")}
        r       = requests.get(BINANCE_24H_URL, params=params, timeout=10)
        r.raise_for_status()

        for item in r.json():
            coin = item["symbol"].replace("USDT", "")
            if coin in coins:
                stats[coin] = {
                    "change_pct": float(item["priceChangePercent"]),
                    "high_24h":   float(item["highPrice"]),
                    "low_24h":    float(item["lowPrice"]),
                    "volume":     float(item["volume"]),
                }
    except Exception as e:
        logger.error(f"24h stats fetch error: {e}")

    return stats


def format_price(coin: str, price: float) -> str:
    """Format price with appropriate decimals per coin"""
    if coin == "BTC":
        return f"${price:,.2f}"
    elif coin in ("ETH", "BNB", "SOL"):
        return f"${price:,.2f}"
    else:
        return f"${price:.4f}"
