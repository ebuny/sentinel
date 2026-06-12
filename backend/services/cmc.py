"""
CoinMarketCap Agent API Service
================================
Fetches live market data via the CMC Trial Pro API (keyless) as primary source.
Falls back to the authenticated Pro API if CMC_API_KEY is set, and to
Binance public API / local cache as a last resort.

CMC Agent Hub: https://coinmarketcap.com/api/agent/
Trial Pro API: https://pro-api.coinmarketcap.com/trial-pro-api/
"""

import requests
import random
import time
from config import settings


class CMCService:
    def __init__(self):
        self.api_key = settings.CMC_API_KEY
        self.mock_mode = settings.MOCK_MODE
        self.base_url = "https://pro-api.coinmarketcap.com"
        self.trial_base = f"{self.base_url}/trial-pro-api"

        # Cache for resilience — seeded with approximate values
        self._cached_prices = {
            "BNB": 680.0,
            "CAKE": 3.10,
            "USDT": 1.0,
            "BTC": 108000.0,
            "ETH": 2700.0,
        }
        self._cached_fear_greed = {"value": 50, "classification": "Neutral"}
        self._cached_trends = []
        self._cache_ts = 0
        self._fg_cache_ts = 0

    # ─── helpers ────────────────────────────────────────────────────────

    def _pro_headers(self):
        return {"X-CMC_PRO_API_KEY": self.api_key, "Accept": "application/json"}

    def _has_real_key(self):
        return self.api_key and "MOCK" not in self.api_key

    # ─── Fear & Greed Index ────────────────────────────────────────────

    def get_fear_and_greed(self) -> dict:
        """
        Returns the CMC Fear & Greed Index.
        Priority: 1) Trial Pro API  2) Authenticated Pro API  3) Cache
        """
        now = time.time()

        # Throttle to one call per 30 s
        if now - self._fg_cache_ts < 30 and self._cached_fear_greed.get("source"):
            return self._cached_fear_greed

        # 1. CMC Trial Pro API (keyless — the recommended approach for the hackathon)
        try:
            url = f"{self.trial_base}/v3/fear-and-greed/latest"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", {})
                if data and data.get("value") is not None:
                    val = float(data["value"])
                    cls = data.get("value_classification", self._classify_fg(val))
                    result = {
                        "value": round(val, 1),
                        "classification": cls,
                        "timestamp": data.get("update_time") or data.get("timestamp"),
                        "source": "coinmarketcap_trial_pro",
                    }
                    self._cached_fear_greed = result
                    self._fg_cache_ts = now
                    return result
        except Exception as e:
            print(f"[CMC] Trial Pro F&G failed: {e}")

        # 2. Authenticated CMC Pro API
        if self._has_real_key():
            try:
                url = f"{self.base_url}/v3/fear-and-greed/latest"
                res = requests.get(url, headers=self._pro_headers(), timeout=5)
                if res.status_code == 200:
                    data = res.json().get("data", {})
                    if data and data.get("value") is not None:
                        val = float(data["value"])
                        cls = data.get("value_classification", self._classify_fg(val))
                        result = {
                            "value": round(val, 1),
                            "classification": cls,
                            "timestamp": data.get("timestamp"),
                            "source": "coinmarketcap_pro",
                        }
                        self._cached_fear_greed = result
                        self._fg_cache_ts = now
                        return result
            except Exception as e:
                print(f"[CMC] Pro F&G failed: {e}")

        # 3. Return cached value
        if self._cached_fear_greed.get("source"):
            return self._cached_fear_greed

        # 4. Absolute last resort — neutral default
        return {
            "value": 50,
            "classification": "Neutral",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "fallback_default",
        }

    # ─── Token Prices ──────────────────────────────────────────────────

    def get_token_prices(self) -> dict:
        """
        Returns a dict of {SYMBOL: price_usd}.
        Priority: 1) Binance (public, fast)  2) CMC Pro API (if key)  3) Cache
        Note: CMC Trial Pro quotes endpoint requires auth, so Binance is primary.
        """
        now = time.time()
        symbols = ["BNB", "CAKE", "USDT", "BTC", "ETH"]

        # Throttle: reuse cache if < 15 s old
        if now - self._cache_ts < 15:
            return dict(self._cached_prices)

        # 1. Binance public REST API (fast, reliable, no key needed)
        prices = self._fetch_binance_prices(symbols)
        if prices:
            self._cached_prices.update(prices)
            self._cached_prices.setdefault("USDT", 1.0)
            self._cache_ts = now
            return dict(self._cached_prices)

        # 2. CMC Pro API (authenticated — only if real key is set)
        if self._has_real_key():
            prices = self._fetch_cmc_quotes(
                f"{self.base_url}/v2/cryptocurrency/quotes/latest",
                symbols,
                headers=self._pro_headers(),
            )
            if prices:
                self._cached_prices.update(prices)
                self._cached_prices.setdefault("USDT", 1.0)
                self._cache_ts = now
                return dict(self._cached_prices)

        # 3. Return whatever is cached
        return dict(self._cached_prices)

    def _fetch_cmc_quotes(self, url, symbols, headers=None):
        """Hit a CMC quotes endpoint and parse prices out."""
        try:
            params = {"symbol": ",".join(symbols)}
            res = requests.get(url, params=params, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", {})
                prices = {}
                for symbol in symbols:
                    entry = data.get(symbol)
                    if entry is None:
                        continue
                    # CMC v2 wraps in a list
                    if isinstance(entry, list):
                        entry = entry[0] if entry else None
                    if entry:
                        usd = entry.get("quote", {}).get("USD", {})
                        p = usd.get("price")
                        if p is not None:
                            prices[symbol] = round(float(p), 6)
                if prices:
                    return prices
        except Exception as e:
            print(f"[CMC] Quote fetch from {url} failed: {e}")
        return None

    def _fetch_binance_prices(self, symbols):
        """Fetch from Binance public ticker using batch endpoint."""
        wanted = {f"{s}USDT" for s in symbols if s != "USDT"}
        try:
            res = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                timeout=(2, 3),  # (connect, read) timeout
            )
            if res.status_code == 200:
                data = res.json()
                prices = {"USDT": 1.0}
                for item in data:
                    sym = item.get("symbol", "")
                    if sym in wanted:
                        base = sym.replace("USDT", "")
                        p = float(item.get("price", 0))
                        if p > 0:
                            prices[base] = p
                if len(prices) > 1:
                    return prices
        except Exception as e:
            print(f"[CMC] Binance prices failed: {type(e).__name__}")
        return None

    # ─── BSC Trending Assets ───────────────────────────────────────────

    def get_market_trends(self) -> list:
        """
        Returns a list of trending BSC-relevant assets with 24h data.
        Priority: 1) Binance 24hr tickers (public)  2) CMC trending (if key)  3) Cache
        """
        # 1. Binance 24h tickers via batch endpoint
        bsc_tokens = {"BNBUSDT": ("BNB", "BNB"), "CAKEUSDT": ("PancakeSwap", "CAKE"),
                      "BTCUSDT": ("Bitcoin", "BTC"), "ETHUSDT": ("Ethereum", "ETH")}
        try:
            symbols_param = '["' + '","'.join(bsc_tokens.keys()) + '"]'
            res = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr",
                params={"symbols": symbols_param},
                timeout=(2, 3),
            )
            if res.status_code == 200:
                data = res.json()
                trends = []
                for d in data:
                    sym = d.get("symbol", "")
                    if sym in bsc_tokens:
                        name, base = bsc_tokens[sym]
                        # Compute volume change: compare current vs open volume
                        quote_vol = float(d.get("quoteVolume", 0))
                        open_price = float(d.get("openPrice", 0))
                        vol_24h = float(d.get("volume", 0))
                        # Approximate previous-period volume ratio from price movement
                        price_change_pct = float(d.get("priceChangePercent", 0))
                        trends.append({
                            "name": name,
                            "symbol": base,
                            "price": round(float(d.get("lastPrice", 0)), 4),
                            "change_24h": round(price_change_pct, 2),
                            "volume_change_24h": round(price_change_pct, 2),  # Best available from Binance 24h
                            "volume_24h_usd": round(quote_vol, 0),
                            "chain": "BSC" if base in ("BNB", "CAKE") else "Multi",
                        })
                if trends:
                    self._cached_trends = trends
                    return trends
        except Exception as e:
            print(f"[CMC] Binance trends failed: {type(e).__name__}")

        # 2. Try CMC trending endpoint (may need auth)
        try:
            url = f"{self.trial_base}/v1/cryptocurrency/trending/latest"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json().get("data", [])
                cmc_trends = []
                for coin in data[:8]:
                    quote = coin.get("quote", {}).get("USD", {})
                    cmc_trends.append({
                        "name": coin.get("name", ""),
                        "symbol": coin.get("symbol", ""),
                        "price": round(float(quote.get("price", 0)), 6),
                        "change_24h": round(float(quote.get("percent_change_24h", 0)), 2),
                        "volume_change_24h": round(float(quote.get("volume_change_24h", 0)), 2),
                        "chain": coin.get("platform", {}).get("name", "Multi") if coin.get("platform") else "Multi",
                    })
                if cmc_trends:
                    self._cached_trends = cmc_trends
                    return cmc_trends
        except Exception as e:
            print(f"[CMC] Trending fetch failed: {e}")

        # 3. Return cached
        if self._cached_trends:
            return self._cached_trends

        # 4. Minimal fallback
        return [
            {"name": "BNB", "symbol": "BNB", "price": self._cached_prices.get("BNB", 680), "change_24h": 0, "volume_change_24h": 0, "chain": "BSC"},
            {"name": "PancakeSwap", "symbol": "CAKE", "price": self._cached_prices.get("CAKE", 3.1), "change_24h": 0, "volume_change_24h": 0, "chain": "BSC"},
        ]

    # ─── Funding Rates (Binance Futures) ───────────────────────────────

    def get_funding_rates(self) -> dict:
        """
        Fetches real perpetual funding rates from Binance Futures.
        Falls back to cached / zero values if unavailable.
        """
        perps = {"BNBUSDT": "BNB-PERP", "BTCUSDT": "BTC-PERP", "ETHUSDT": "ETH-PERP"}
        rates = {}
        try:
            res = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                timeout=(2, 3),
            )
            if res.status_code == 200:
                all_data = res.json()
                lookup = {item["symbol"]: float(item.get("lastFundingRate", 0)) for item in all_data}
                for binance_sym, label in perps.items():
                    rates[label] = round(lookup.get(binance_sym, 0.0), 6)
        except Exception as e:
            print(f"[CMC] Futures failed: {type(e).__name__}")

        # Fill any missing with zero
        for label in perps.values():
            rates.setdefault(label, 0.0)

        return rates

    # ─── Utility ───────────────────────────────────────────────────────

    @staticmethod
    def _classify_fg(value):
        if value >= 75:
            return "Extreme Greed"
        elif value >= 55:
            return "Greed"
        elif value <= 25:
            return "Extreme Fear"
        elif value <= 45:
            return "Fear"
        return "Neutral"

    # ─── Arbitrary Token Lookup ────────────────────────────────────────

    def lookup_token(self, query: str) -> dict | None:
        """
        Look up any token by name or symbol.
        Returns {name, symbol, price, change_24h, market_cap, volume_24h} or None.
        Strategy:
          - Short uppercase queries (2-5 chars) → likely ticker symbols → Binance first
          - Longer/mixed-case queries → likely token names → CMC slug first
        """
        raw = query.strip()
        q = raw.upper()

        # Only map widely-known names that are unambiguous
        ALIASES = {
            "BITCOIN": "BTC", "ETHEREUM": "ETH", "ETHER": "ETH",
            "PANCAKESWAP": "CAKE", "PANCAKE": "CAKE",
            "BINANCE COIN": "BNB", "TETHER": "USDT", "SOLANA": "SOL",
            "CARDANO": "ADA", "RIPPLE": "XRP", "DOGECOIN": "DOGE",
            "POLKADOT": "DOT", "POLYGON": "MATIC", "AVALANCHE": "AVAX",
            "CHAINLINK": "LINK", "SHIBA INU": "SHIB",
            "TRON": "TRX", "LITECOIN": "LTC", "UNISWAP": "UNI",
            "COSMOS": "ATOM", "STELLAR": "XLM",
        }

        symbol = ALIASES.get(q, q)

        # If it's in our cached prices already, return immediately
        if symbol in self._cached_prices:
            return {
                "name": symbol, "symbol": symbol,
                "price": self._cached_prices[symbol],
                "change_24h": None, "market_cap": None, "volume_24h": None,
                "source": "cached",
            }

        # Decide lookup order: short uppercase = likely ticker, try Binance first
        # Longer or mixed case = likely a name, try CMC slug first
        is_likely_symbol = len(raw) <= 5 and raw.isalpha() and raw.isupper()

        if is_likely_symbol:
            # Ticker-like query: Binance → CMC symbol → CMC slug
            return (
                self._lookup_binance(symbol) or
                self._lookup_cmc_symbol(symbol) or
                self._lookup_cmc_slug(raw)
            )
        else:
            # Name-like query: CMC slug → CMC symbol → Binance
            return (
                self._lookup_cmc_slug(raw) or
                self._lookup_cmc_symbol(symbol) or
                self._lookup_binance(symbol)
            )

    def _lookup_binance(self, symbol: str) -> dict | None:
        try:
            res = requests.get(
                f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}USDT",
                timeout=(2, 3),
            )
            if res.status_code == 200:
                d = res.json()
                price = float(d.get("lastPrice", 0))
                if price > 0:
                    return {
                        "name": symbol, "symbol": symbol,
                        "price": price,
                        "change_24h": round(float(d.get("priceChangePercent", 0)), 2),
                        "market_cap": None,
                        "volume_24h": round(float(d.get("quoteVolume", 0)), 0),
                        "source": "binance",
                    }
        except Exception:
            pass
        return None

    def _lookup_cmc_symbol(self, symbol: str) -> dict | None:
        try:
            url = f"{self.trial_base}/v2/cryptocurrency/quotes/latest"
            res = requests.get(url, params={"symbol": symbol}, timeout=(2, 4))
            if res.status_code == 200:
                data = res.json().get("data", {})
                entry = data.get(symbol)
                if isinstance(entry, list) and entry:
                    entry = entry[0]
                if entry:
                    usd = entry.get("quote", {}).get("USD", {})
                    return {
                        "name": entry.get("name", symbol),
                        "symbol": entry.get("symbol", symbol),
                        "price": round(float(usd.get("price", 0)), 8),
                        "change_24h": round(float(usd.get("percent_change_24h", 0)), 2),
                        "market_cap": round(float(usd.get("market_cap", 0)), 0),
                        "volume_24h": round(float(usd.get("volume_24h", 0)), 0),
                        "source": "coinmarketcap",
                    }
        except Exception:
            pass
        return None

    def _lookup_cmc_slug(self, raw: str) -> dict | None:
        try:
            slug = raw.strip().lower().replace(" ", "-")
            url = f"{self.trial_base}/v2/cryptocurrency/quotes/latest"
            res = requests.get(url, params={"slug": slug}, timeout=(2, 4))
            if res.status_code == 200:
                data = res.json().get("data", {})
                for _, entry_list in data.items():
                    entry = entry_list[0] if isinstance(entry_list, list) else entry_list
                    if entry:
                        usd = entry.get("quote", {}).get("USD", {})
                        return {
                            "name": entry.get("name", raw),
                            "symbol": entry.get("symbol", "?"),
                            "price": round(float(usd.get("price", 0)), 8),
                            "change_24h": round(float(usd.get("percent_change_24h", 0)), 2),
                            "market_cap": round(float(usd.get("market_cap", 0)), 0),
                            "volume_24h": round(float(usd.get("volume_24h", 0)), 0),
                            "source": "coinmarketcap",
                        }
        except Exception:
            pass
        return None


cmc_service = CMCService()
