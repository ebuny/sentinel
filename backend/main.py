"""
BNB Sentiment Sentinel — FastAPI Backend
==========================================
Autonomous trading agent powered by:
  • CoinMarketCap Agent API  (market intelligence)
  • Trust Wallet Agent Kit   (on-chain execution)
  • BNB AI Agent SDK         (identity & commerce)

Endpoints:
  GET  /                → server status
  GET  /api/market       → Fear & Greed, prices, trends, funding rates
  GET  /api/portfolio    → wallet balances, identity, recent trades
  GET  /api/strategy     → current strategy settings
  POST /api/strategy     → update strategy
  GET  /api/strategy/status → autonomous loop health & last action
  GET  /api/jobs         → ERC-8183 commerce job list
  POST /api/jobs         → trigger a mock escrow job
  POST /api/chat         → NLP copilot interface
"""

import sys
# Fix Windows console encoding for Unicode characters
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


import uvicorn
import json
import random
import threading
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import settings
import database
from services.cmc import cmc_service
from services.twak import twak_service
from services.commerce import commerce_service


# ─── Autonomous strategy loop state (visible to /api/strategy/status) ──
_strategy_loop_state = {
    "running": False,
    "last_check_time": None,
    "last_action": None,
    "last_action_time": None,
    "consecutive_errors": 0,
    "loop_health": "STARTING",
}
_strategy_loop_state_lock = threading.Lock()

def _update_loop_state(**kwargs):
    with _strategy_loop_state_lock:
        _strategy_loop_state.update(kwargs)


# ─── Lifespan: start background threads only once ──────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the autonomous strategy loop once on server start (not per reload)."""
    _print_startup_banner()
    thread = threading.Thread(target=_autonomous_strategy_loop, daemon=True)
    thread.start()
    yield
    # Shutdown: nothing to clean up (daemon thread dies with process)


app = FastAPI(
    title="BNB Sentiment Sentinel API",
    description="Backend API for the BNB Sentiment Sentinel autonomous trading agent",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for frontend (flexible for deployment)
_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# Allow any origin in mock/dev mode so deployed frontends work
if settings.MOCK_MODE:
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not settings.MOCK_MODE,  # credentials can't be used with wildcard
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount live ERC-8183 Commerce server if SDK is available
commerce_service.mount_live_app(app)


# ─── Request / Response schemas ────────────────────────────────────────

class StrategyUpdateRequest(BaseModel):
    strategy: str
    risk_guard: bool


class ChatMessageRequest(BaseModel):
    message: str


class MockJobRequest(BaseModel):
    description: str
    budget: float


# ─── Health / Status ───────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {
        "name": "BNB Sentiment Sentinel Agent Server",
        "status": "ONLINE",
        "mock_mode": settings.MOCK_MODE,
        "twak_cli": twak_service.twak_available,
        "erc8004_identity": settings.ERC8004_REGISTRY_ADDR,
        "erc8183_commerce": settings.ERC8183_COMMERCE_ADDR,
    }


# ─── Market Intelligence ──────────────────────────────────────────────

@app.get("/api/market")
def get_market_data():
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {
        "fear_greed": {"value": 50, "classification": "Neutral", "source": "fallback"},
        "prices": {},
        "trends": [],
        "funding_rates": {},
    }

    def fetch_fg():
        return cmc_service.get_fear_and_greed()

    def fetch_prices():
        return cmc_service.get_token_prices()

    def fetch_trends():
        return cmc_service.get_market_trends()

    def fetch_funding():
        return cmc_service.get_funding_rates()

    tasks = {
        "fear_greed": fetch_fg,
        "prices": fetch_prices,
        "trends": fetch_trends,
        "funding_rates": fetch_funding,
    }

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fn): key for key, fn in tasks.items()}
            for future in as_completed(futures, timeout=10):
                key = futures[future]
                try:
                    data = future.result(timeout=8)
                    if data is not None:
                        results[key] = data
                except Exception as e:
                    print(f"[Market] {key} fetch error: {type(e).__name__}")
    except Exception as e:
        print(f"[Market] Parallel fetch timeout: {type(e).__name__}")

    return results


# ─── Portfolio ─────────────────────────────────────────────────────────

@app.get("/api/portfolio")
def get_portfolio_data():
    try:
        balances = twak_service.get_balances()
        identity = commerce_service.register_identity()
        trades = database.get_trades(limit=10)

        prices = cmc_service.get_token_prices()
        usd_value = sum(bal * prices.get(token, 1.0) for token, bal in balances.items())

        return {
            "balances": balances,
            "estimated_usd_value": round(usd_value, 2),
            "identity": identity,
            "recent_trades": trades,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Portfolio data fetch error: {str(e)}")


# ─── Strategy ─────────────────────────────────────────────────────────

@app.get("/api/strategy")
def get_strategy():
    return {
        "strategy": database.get_state("strategy", "BALANCED"),
        "risk_guard": database.get_state("risk_guard", "true") == "true",
        "target_tokens": json.loads(database.get_state("target_tokens", '["BNB", "CAKE", "USDT"]')),
    }


@app.post("/api/strategy")
def update_strategy(req: StrategyUpdateRequest):
    database.set_state("strategy", req.strategy)
    database.set_state("risk_guard", "true" if req.risk_guard else "false")
    return {"status": "SUCCESS", "strategy": req.strategy, "risk_guard": req.risk_guard}


@app.get("/api/strategy/status")
def get_strategy_status():
    """Expose the autonomous strategy loop health to the frontend and judges."""
    with _strategy_loop_state_lock:
        state = dict(_strategy_loop_state)
    state["cooldown_seconds"] = settings.AGENT_STRATEGY_COOLDOWN_SECONDS
    state["mock_mode"] = settings.MOCK_MODE
    return state


# ─── ERC-8183 Jobs ────────────────────────────────────────────────────

@app.get("/api/jobs")
def get_jobs_list():
    return database.get_jobs()


@app.post("/api/jobs")
def create_mock_job(req: MockJobRequest):
    job_id = commerce_service.trigger_mock_client_job(req.description, req.budget)
    return {
        "status": "FUNDED",
        "job_id": job_id,
        "message": f"Job funded on-chain with {req.budget} BNB escrow. Sentinel is starting work.",
    }


# ─── NLP Chat Copilot ─────────────────────────────────────────────────

@app.post("/api/chat")
def handle_chat_message(req: ChatMessageRequest):
    import re

    msg_raw = req.message.strip()
    msg = msg_raw.lower()

    prices = cmc_service.get_token_prices()
    balances = twak_service.get_balances()
    fear_greed = cmc_service.get_fear_and_greed()

    response_text = ""
    action_taken = None

    # ── Swap / Buy / Sell ──
    if any(kw in msg for kw in ["swap ", "buy ", "sell "]):
        try:
            words = msg.split()
            amount = 0.0
            for w in words:
                try:
                    amount = float(w)
                    break
                except ValueError:
                    continue

            # Generalized token pair detection: find any two recognized tokens
            SUPPORTED_TOKENS = {"bnb", "cake", "usdt", "btc", "eth", "sol", "ada",
                                "xrp", "doge", "dot", "matic", "avax", "link", "shib",
                                "trx", "ltc", "uni", "atom", "xlm", "near", "apt",
                                "arb", "op", "sui", "sei", "tia", "inj", "fil",
                                "aave", "mkr", "pepe", "bonk", "floki", "usdc", "dai"}

            # Extract tokens mentioned in order
            found_tokens = []
            for w in words:
                w_clean = w.strip(".,!?;:'\"")
                if w_clean in SUPPORTED_TOKENS and w_clean.upper() not in [t for t in found_tokens]:
                    found_tokens.append(w_clean.upper())
            # Also check for "to" keyword pattern: "swap X TOKEN1 to TOKEN2"
            if len(found_tokens) < 2:
                # Try stripping prepositions
                for w in words:
                    w_clean = w.strip(".,!?;:'\"")
                    if w_clean in SUPPORTED_TOKENS:
                        tok = w_clean.upper()
                        if tok not in found_tokens:
                            found_tokens.append(tok)

            token_in, token_out = "", ""
            if len(found_tokens) >= 2:
                token_in, token_out = found_tokens[0], found_tokens[1]

            if amount > 0 and token_in and token_out:
                res = twak_service.execute_swap(token_in, token_out, amount, strategy="MANUAL_NLP")
                if res["status"] == "SUCCESS":
                    mode_tag = "LIVE" if res.get("mode") == "live" else "SIMULATED"
                    response_text = (
                        f"**Swap Executed ({mode_tag})**\n\n"
                        f"Converted **{amount} {token_in}** -> **{res['amount_out']} {token_out}**\n"
                        f"Transaction Hash: `{res['tx_hash']}`\n"
                        f"Slippage/Fees: 0.5%"
                    )
                    action_taken = "SWAP"
                else:
                    response_text = f"**Swap Failed:** {res.get('error')}"
            else:
                response_text = "I couldn't parse the swap details. Try: `swap 0.5 BNB to CAKE` or `swap 50 USDT to BNB`"
        except Exception as e:
            response_text = f"Error processing swap: {str(e)}"

    # ── Rebalance ──
    elif any(kw in msg for kw in ["rebalance", "rotate"]):
        strategy = database.get_state("strategy", "BALANCED")
        response_text = f"**Initiating Rebalancing ({strategy} Strategy)**...\n\n"

        targets = {
            "CONSERVATIVE": {"BNB": 0.30, "CAKE": 0.10, "USDT": 0.60},
            "AGGRESSIVE": {"BNB": 0.50, "CAKE": 0.40, "USDT": 0.10},
        }.get(strategy, {"BNB": 0.40, "CAKE": 0.20, "USDT": 0.40})

        usd_value = sum(bal * prices.get(tok, 1.0) for tok, bal in balances.items())
        target_usd = {tok: usd_value * pct for tok, pct in targets.items()}
        current_usd = {tok: bal * prices.get(tok, 1.0) for tok, bal in balances.items()}
        diffs = {tok: target_usd[tok] - current_usd.get(tok, 0) for tok in targets}

        sorted_diffs = sorted(diffs.items(), key=lambda x: x[1])
        excess_token, excess_val = sorted_diffs[0]
        deficit_token, deficit_val = sorted_diffs[-1]
        val_to_swap = min(abs(excess_val), deficit_val)

        if val_to_swap > 5.0:
            amount_in = val_to_swap / prices.get(excess_token, 1.0)
            res = twak_service.execute_swap(excess_token, deficit_token, amount_in, strategy=f"REBALANCE_{strategy}")
            if res["status"] == "SUCCESS":
                action_taken = "REBALANCE"
                response_text += (
                    f"Rotated **{round(amount_in, 4)} {excess_token}** -> **{deficit_token}** (~${round(val_to_swap, 2)})\n\n"
                    f"Target allocation: {targets}"
                )
            else:
                response_text += f"Failed: {res.get('error')}"
        else:
            response_text += "Portfolio is within threshold. No action required."

    # ── Market Sentiment ──
    elif any(kw in msg for kw in ["sentiment", "fear", "greed", "market overview", "market mood"]):
        fg = fear_greed
        response_text = (
            f"**Market Intelligence (via CoinMarketCap Agent API)**\n\n"
            f"- **Fear & Greed Index:** `{fg['value']}` ({fg['classification']})\n"
            f"- **Data Source:** {fg.get('source', 'unknown')}\n"
            f"- **Prices:**\n"
            f"  - BNB: `${prices.get('BNB', 0):.2f}`\n"
            f"  - CAKE: `${prices.get('CAKE', 0):.4f}`\n"
            f"  - BTC: `${prices.get('BTC', 0):,.2f}`\n"
            f"  - ETH: `${prices.get('ETH', 0):,.2f}`\n\n"
            f"**Strategy Tip:** "
        )
        if fg["value"] > 75:
            response_text += "Market in **Extreme Greed** -- consider rotating to USDT stablecoins."
        elif fg["value"] < 35:
            response_text += "Market in **Fear** -- potential DCA accumulation zone for BNB and CAKE."
        else:
            response_text += "Sentiment stable -- balanced or grid-trading strategy is optimal."

    # ── Wallet / Portfolio ──
    elif any(kw in msg for kw in ["balance", "portfolio", "wallet", "holdings"]):
        bal_str = "\n".join(
            f"  - **{tok}**: `{bal:.4f}` (~${bal * prices.get(tok, 1.0):.2f})"
            for tok, bal in balances.items()
        )
        usd_total = sum(bal * prices.get(tok, 1.0) for tok, bal in balances.items())
        response_text = (
            f"**Trust Wallet Balances (TWAK Scoped)**\n\n{bal_str}\n\n"
            f"Total: **${usd_total:,.2f} USD**"
        )

    # ── Identity ──
    elif any(kw in msg for kw in ["who are you", "identity", "contract", "what are you"]):
        identity = commerce_service.register_identity()
        response_text = (
            f"**I am the BNB Sentiment Sentinel**\n\n"
            f"- **On-Chain Identity (ERC-8004):** Token ID `{identity['token_id']}`\n"
            f"- **Registry Contract:** `{identity['registry_contract']}`\n"
            f"- **Commerce (ERC-8183):** `{settings.ERC8183_COMMERCE_ADDR}`\n"
            f"- **Agent Wallet:** `{identity['agent_wallet']}`\n"
            f"- **Mode:** {identity['mode']}\n\n"
            f"Hire me by locking a budget in the on-chain escrow."
        )

    # ── Price Query for ANY Token ──
    # Matches: "price of X", "how much is X", "what is X price", "X price", "price X"
    elif _detect_price_query(msg):
        token_name = _extract_token_name(msg)
        if token_name:
            result = cmc_service.lookup_token(token_name)
            if result and result["price"] > 0:
                price_fmt = _format_price(result["price"])
                response_text = f"**{result['name']} ({result['symbol']})**\n\n"
                response_text += f"- **Price:** `{price_fmt}`\n"
                if result.get("change_24h") is not None:
                    arrow = "+" if result["change_24h"] >= 0 else ""
                    response_text += f"- **24h Change:** `{arrow}{result['change_24h']}%`\n"
                if result.get("market_cap") and result["market_cap"] > 0:
                    response_text += f"- **Market Cap:** `${result['market_cap']:,.0f}`\n"
                if result.get("volume_24h") and result["volume_24h"] > 0:
                    response_text += f"- **24h Volume:** `${result['volume_24h']:,.0f}`\n"
                response_text += f"- **Source:** {result.get('source', 'live')}"
            else:
                response_text = f"Could not find pricing data for **{token_name}**. Try using the token's ticker symbol (e.g., BTC, ETH, SOL)."
        else:
            response_text = "Which token would you like to check? Try: `price of BNB` or `what is SOL worth?`"
    # ── Competition Registration ──
    elif any(kw in msg for kw in ["register for competition", "register hackathon", "competition_register", "compete register", "register"]):
        res = twak_service.register_for_competition()
        if res and res.get("success"):
            mode_tag = "LIVE" if res.get("mode") == "live" else "SIMULATED"
            identity = commerce_service.register_identity()
            agent_wallet = identity.get("agent_wallet", "unknown")
            response_text = (
                f"**On-Chain Competition Registration ({mode_tag})**\n\n"
                f"Successfully submitted the registration transaction for the BNB Hackathon!\n\n"
                f"- **Agent Wallet Address:** `{agent_wallet}`\n"
                f"- **Competition Contract:** `{res['contract']}`\n"
                f"- **Transaction Hash:** `{res['tx_hash']}`\n\n"
                f"Your agent is registered to trade in the competition."
            )
        else:
            response_text = (
                f"**Registration Attempt Failed**\n\n"
                f"I could not execute the on-chain registration because the Trust Wallet Agent Kit (TWAK) CLI is not installed or configured.\n\n"
                f"To register your agent, please run this on your command line:\n"
                f"```bash\n"
                f"twak compete register\n"
                f"```"
            )

    # ── Help ──
    elif any(kw in msg for kw in ["help", "what can you do", "commands", "how to use"]):
        response_text = (
            "**Sentinel Commands**\n\n"
            "- `price of [token]` -- Look up any crypto price\n"
            "- `what is the market sentiment?` -- Fear & Greed + prices\n"
            "- `show my balances` -- Trust Wallet portfolio\n"
            "- `swap 0.5 BNB to CAKE` -- Execute a token swap\n"
            "- `rebalance my wallet` -- Auto-rebalance by strategy\n"
            "- `who are you?` -- Agent identity info\n"
            "- `register for competition` -- Submit on-chain hackathon registration\n\n"
            "I can look up the price of **any cryptocurrency** -- just ask!"
        )

    # ── Intelligent Default — attempt price lookup as last resort ──
    else:
        # Try to extract any word that could be a token name
        token_guess = _guess_token_from_message(msg)
        if token_guess:
            result = cmc_service.lookup_token(token_guess)
            if result and result["price"] > 0:
                price_fmt = _format_price(result["price"])
                response_text = f"**{result['name']} ({result['symbol']})**\n\n"
                response_text += f"- **Price:** `{price_fmt}`\n"
                if result.get("change_24h") is not None:
                    arrow = "+" if result["change_24h"] >= 0 else ""
                    response_text += f"- **24h Change:** `{arrow}{result['change_24h']}%`\n"
                if result.get("source"):
                    response_text += f"- **Source:** {result['source']}"
            else:
                response_text = (
                    f"I'm not sure what you mean by **\"{msg_raw}\"**.\n\n"
                    "Try asking me:\n"
                    "- `price of BNB` or `what is bitcoin worth?`\n"
                    "- `show my balances`\n"
                    "- `swap 0.2 BNB to CAKE`\n"
                    "- `what is the market sentiment?`\n"
                    "- `rebalance my wallet`\n"
                    "- `help` for all commands"
                )
        else:
            response_text = (
                f"I'm not sure how to help with **\"{msg_raw}\"**.\n\n"
                "Try asking me:\n"
                "- `price of BNB` or `what is bitcoin worth?`\n"
                "- `show my balances`\n"
                "- `swap 0.2 BNB to CAKE`\n"
                "- `what is the market sentiment?`\n"
                "- `rebalance my wallet`\n"
                "- `help` for all commands"
            )

    return {
        "response": response_text,
        "action": action_taken,
        "agent_state": {
            "strategy": database.get_state("strategy", "BALANCED"),
            "risk_guard": database.get_state("risk_guard", "true") == "true",
        },
    }


# ─── NLP Helper Functions ──────────────────────────────────────────────

def _format_price(price: float) -> str:
    """Format a price value appropriately based on magnitude."""
    if price >= 1:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:,.4f}"
    else:
        return f"${price:,.8f}".rstrip("0").rstrip(".")


def _detect_price_query(msg: str) -> bool:
    """Detect if the message is asking about a token price."""
    import re
    patterns = [
        r"price\s+of\b",          # "price of X"
        r"price\s+for\b",         # "price for X"
        r"\bprice\b.*\?",         # "what is X price?"
        r"how\s+much\s+is\b",     # "how much is X"
        r"what\s+is\b.*\bworth\b", # "what is X worth"
        r"what\s+is\b.*\bprice\b", # "what is X price"
        r"what\s+is\b.*\bcost\b",  # "what is X cost"
        r"what\s+is\b.*\bvalue\b", # "what is X value"
        r"\bcost\s+of\b",         # "cost of X"
        r"\bvalue\s+of\b",        # "value of X"
        r"how\s+much\s+does\b",   # "how much does X cost"
        r"what\s+does\b.*\bcost\b", # "what does X cost"
        r"\bprice\b$",            # just "price" at end
        r"^\w+\s+price\b",        # "BNB price"
        r"\bquote\b",             # "quote for X"
        r"\bcheck\b.*\bprice\b",  # "check the price"
        r"\blookup\b",            # "lookup X"
        r"\bwhat\s+is\b",         # "what is X" (general)
    ]
    return any(re.search(p, msg) for p in patterns)


def _extract_token_name(msg: str) -> str | None:
    """Extract the token name from a price query."""
    import re

    # Remove common question words and prepositions
    noise = [
        "what", "is", "the", "price", "of", "for", "how", "much",
        "does", "cost", "worth", "value", "current", "today",
        "right", "now", "check", "show", "me", "tell", "get",
        "can", "you", "please", "a", "an", "in", "usd", "dollars",
        "quote", "lookup", "look", "up", "whats", "what's",
    ]

    # Clean message
    cleaned = re.sub(r"[?!.,;:'\"]", "", msg.lower())
    words = cleaned.split()

    # Filter out noise words
    tokens = [w for w in words if w not in noise and len(w) >= 2]

    if tokens:
        # If multiple words remain, try them as a phrase first, then individual
        candidate = " ".join(tokens)
        if len(tokens) <= 3:
            return candidate
        # If too many tokens, just take the last significant one
        return tokens[-1]

    return None


def _guess_token_from_message(msg: str) -> str | None:
    """Last resort: try to guess if any word in the message is a token name."""
    import re

    # Known token symbols and names
    KNOWN = {
        "btc", "eth", "bnb", "sol", "ada", "xrp", "doge", "dot",
        "matic", "avax", "link", "shib", "trx", "ltc", "uni", "atom",
        "xlm", "near", "apt", "arb", "op", "sui", "sei", "tia",
        "inj", "fil", "aave", "mkr", "cake", "pepe", "bonk", "floki",
        "astr", "aster", "bitcoin", "ethereum", "solana", "cardano",
        "ripple", "dogecoin", "polkadot", "polygon", "avalanche",
        "chainlink", "tron", "litecoin", "uniswap", "cosmos",
        "stellar", "aptos", "arbitrum", "optimism", "celestia",
        "injective", "filecoin", "pancakeswap", "pancake", "usdt",
        "usdc", "dai", "wbtc", "steth",
    }

    words = re.sub(r"[?!.,;:'\"]", "", msg.lower()).split()
    for word in words:
        if word in KNOWN:
            return word

    return None


# ─── Autonomous Strategy Loop ─────────────────────────────────────────

def _autonomous_strategy_loop():
    """
    Background thread that periodically checks market conditions and
    auto-rebalances if the Risk Guard is enabled and conditions are met.
    Runs every 60 seconds with exponential backoff on errors.
    """
    print("[Sentinel] Starting autonomous strategy loop (60s interval)...")
    _update_loop_state(running=True, loop_health="STARTING")
    time.sleep(10)  # Short initial delay — let the server start serving first

    base_interval = 60
    current_interval = base_interval
    max_interval = 300  # 5-minute cap on backoff

    while True:
        try:
            _update_loop_state(last_check_time=time.strftime("%Y-%m-%dT%H:%M:%SZ"))

            risk_guard = database.get_state("risk_guard", "true") == "true"
            if not risk_guard:
                _update_loop_state(loop_health="IDLE_GUARD_OFF")
                current_interval = base_interval  # reset backoff
                time.sleep(base_interval)
                continue

            fg = cmc_service.get_fear_and_greed()
            strategy = database.get_state("strategy", "BALANCED")

            # Check strategy cooldown
            last_exec_str = database.get_state("last_strategy_execution", "0")
            try:
                last_exec = float(last_exec_str)
            except ValueError:
                last_exec = 0.0

            current_time = time.time()
            cooldown = settings.AGENT_STRATEGY_COOLDOWN_SECONDS
            is_cooldown_active = (current_time - last_exec) < cooldown

            # Successful API call — reset backoff
            current_interval = base_interval
            _update_loop_state(consecutive_errors=0, loop_health="MONITORING")

            # ── Risk Guard: auto-rotate to USDT when Extreme Greed ──
            if fg["value"] > 78:
                if is_cooldown_active:
                    remaining = int(cooldown - (current_time - last_exec))
                    print(f"[Sentinel] Extreme Greed zone active, cooldown active ({remaining}s remaining)")
                    _update_loop_state(loop_health="COOLDOWN_ACTIVE")
                    time.sleep(base_interval)
                    continue

                print(f"[Sentinel] Extreme Greed ({fg['value']}) detected — triggering risk rotation")
                balances = twak_service.get_balances()
                prices = cmc_service.get_token_prices()

                # Sell 20% of non-USDT holdings to USDT
                executed_any = False
                for token in ["BNB", "CAKE"]:
                    bal = balances.get(token, 0)
                    sell_amount = bal * 0.20
                    if sell_amount * prices.get(token, 0) > 5:  # min $5 trade
                        res = twak_service.execute_swap(token, "USDT", sell_amount, strategy="RISK_GUARD")
                        if res["status"] == "SUCCESS":
                            print(f"[Sentinel] Risk guard: sold {sell_amount:.4f} {token} -> USDT")
                            executed_any = True

                if executed_any:
                    database.set_state("last_strategy_execution", str(time.time()))
                    _update_loop_state(
                        last_action="RISK_GUARD_ROTATION",
                        last_action_time=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )

            # ── Accumulation: DCA into BNB/CAKE during Fear ──
            elif fg["value"] < 25:
                if is_cooldown_active:
                    remaining = int(cooldown - (current_time - last_exec))
                    print(f"[Sentinel] Extreme Fear zone active, cooldown active ({remaining}s remaining)")
                    _update_loop_state(loop_health="COOLDOWN_ACTIVE")
                    time.sleep(base_interval)
                    continue

                print(f"[Sentinel] Extreme Fear ({fg['value']}) — DCA accumulation opportunity")
                balances = twak_service.get_balances()
                usdt_bal = balances.get("USDT", 0)

                if usdt_bal > 20:  # min $20 to DCA
                    dca_amount = min(usdt_bal * 0.10, 50)  # 10% of USDT, max $50
                    target = "BNB" if strategy == "AGGRESSIVE" else "CAKE" if strategy == "CONSERVATIVE" else "BNB"
                    res = twak_service.execute_swap("USDT", target, dca_amount, strategy="DCA_FEAR")
                    if res["status"] == "SUCCESS":
                        print(f"[Sentinel] DCA: bought {target} with {dca_amount:.2f} USDT")
                        database.set_state("last_strategy_execution", str(time.time()))
                        _update_loop_state(
                            last_action="DCA_ACCUMULATION",
                            last_action_time=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        )

        except Exception as e:
            # Exponential backoff on errors
            with _strategy_loop_state_lock:
                _strategy_loop_state["consecutive_errors"] += 1
                err_count = _strategy_loop_state["consecutive_errors"]
            _update_loop_state(loop_health=f"ERROR (x{err_count})")

            current_interval = min(current_interval * 2, max_interval)
            print(f"[Sentinel] Strategy loop error: {e} — backing off to {current_interval}s")

        time.sleep(current_interval)


# ─── Startup Banner ───────────────────────────────────────────────────

def _print_startup_banner():
    """Print a clear startup summary for judges and developers."""
    mode = "MOCK (simulated)" if settings.MOCK_MODE else "LIVE (on-chain)"
    twak_status = "DETECTED" if twak_service.twak_available else "NOT FOUND (simulated)"
    sdk_status = "LOADED" if commerce_service.mock_mode is False else "SIMULATED"
    cmc_key = "Trial Pro (keyless)" if not cmc_service._has_real_key() else "Pro API (authenticated)"

    print("\n" + "=" * 60)
    print("  BNB SENTIMENT SENTINEL — Autonomous Trading Agent")
    print("=" * 60)
    print(f"  Mode:           {mode}")
    print(f"  TWAK CLI:       {twak_status}")
    print(f"  BNB Agent SDK:  {sdk_status}")
    print(f"  CMC Data:       {cmc_key}")
    print(f"  Server:         http://{settings.HOST}:{settings.PORT}")
    print(f"  ERC-8004:       {settings.ERC8004_REGISTRY_ADDR}")
    print(f"  ERC-8183:       {settings.ERC8183_COMMERCE_ADDR}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
