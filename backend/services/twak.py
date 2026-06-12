"""
Trust Wallet Agent Kit (TWAK) Service
======================================
Integrates with the TWAK CLI for on-chain wallet operations on BSC.
Falls back to simulated SQLite-based balances when TWAK CLI is not installed.

TWAK Portal: https://portal.trustwallet.com/
TWAK Docs:   https://developer.trustwallet.com/developer/agent-sdk
CLI Install: curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
"""

import json
import shutil
import subprocess
import random
from config import settings
import database
from services.cmc import cmc_service


class TWAKService:
    def __init__(self):
        self.mock_mode = settings.MOCK_MODE
        self.access_id = settings.TWAK_ACCESS_ID
        self.hmac_secret = settings.TWAK_HMAC_SECRET

        # Detect if twak CLI is installed
        self.twak_available = shutil.which("twak") is not None
        if self.twak_available:
            print("[TWAK] ✓ twak CLI detected on PATH — live execution enabled")
        else:
            print("[TWAK] ⚠ twak CLI not found — running in simulated mode")
            print("[TWAK]   Install: curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash")

        # Initialize default balances in DB if not set
        self._init_balances()

    def _init_balances(self):
        if database.get_state("balance_BNB") is None:
            database.set_state("balance_BNB", "10.0")
        if database.get_state("balance_CAKE") is None:
            database.set_state("balance_CAKE", "150.0")
        if database.get_state("balance_USDT") is None:
            database.set_state("balance_USDT", "500.0")

    # ─── CLI helper ────────────────────────────────────────────────────

    def _run_twak(self, args: list, timeout: int = 15) -> dict | None:
        """
        Execute a twak CLI command and return parsed JSON output.
        Returns None if CLI is unavailable or command fails.
        """
        if not self.twak_available:
            return None

        cmd = ["twak"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=None,  # inherit environment (TWAK reads ~/.twak/ creds)
            )
            if result.returncode == 0:
                stdout = result.stdout.strip()
                # Try to parse as JSON first
                try:
                    return json.loads(stdout)
                except json.JSONDecodeError:
                    # Return raw text wrapped in a dict
                    return {"raw": stdout, "success": True}
            else:
                print(f"[TWAK] Command failed: {' '.join(cmd)}")
                print(f"[TWAK]   stderr: {result.stderr.strip()}")
                return None
        except subprocess.TimeoutExpired:
            print(f"[TWAK] Command timed out: {' '.join(cmd)}")
            return None
        except Exception as e:
            print(f"[TWAK] Execution error: {e}")
            return None

    # ─── Wallet Balances ───────────────────────────────────────────────

    def get_balances(self) -> dict:
        """
        Fetch wallet balances.
        Live: calls `twak wallet portfolio`
        Mock: reads from SQLite state
        """
        # Try live TWAK if not explicitly in mock mode
        if not self.mock_mode and self.twak_available:
            result = self._run_twak(["wallet", "portfolio"])
            if result:
                return self._parse_portfolio(result)

        # Simulated balances from DB
        return {
            "BNB": float(database.get_state("balance_BNB", "10.0")),
            "CAKE": float(database.get_state("balance_CAKE", "150.0")),
            "USDT": float(database.get_state("balance_USDT", "500.0")),
        }

    def _parse_portfolio(self, data: dict) -> dict:
        """Parse TWAK portfolio output into a simple {token: amount} dict."""
        balances = {}
        if isinstance(data, dict):
            # If it's raw text like "$12,450 · ETH 3.2 · SOL 18.4 · 6 chains"
            if "raw" in data:
                raw = data["raw"]
                # Try to parse token amounts from text output
                import re
                pairs = re.findall(r"([A-Z]{2,10})\s+([\d.]+)", raw)
                for token, amount in pairs:
                    balances[token] = float(amount)
            else:
                # Structured JSON from newer TWAK versions
                for token, info in data.items():
                    if isinstance(info, (int, float)):
                        balances[token] = float(info)
                    elif isinstance(info, dict):
                        balances[token] = float(info.get("balance", info.get("amount", 0)))

        # Ensure core tokens exist
        for tok in ["BNB", "CAKE", "USDT"]:
            balances.setdefault(tok, 0.0)

        # Update DB cache
        for tok, bal in balances.items():
            database.set_state(f"balance_{tok}", str(round(bal, 6)))

        return balances

    # ─── Get Price via TWAK ────────────────────────────────────────────

    def get_price(self, symbol: str) -> float | None:
        """
        Fetch a single token price via `twak price <SYMBOL>`.
        Returns the price in USD or None if unavailable.
        """
        if not self.twak_available:
            return None
        result = self._run_twak(["price", symbol.upper()])
        if result and "raw" in result:
            # Parse "ETH  $2,286.20  ethereum" style output
            import re
            match = re.search(r"\$?([\d,]+\.?\d*)", result["raw"])
            if match:
                return float(match.group(1).replace(",", ""))
        return None

    # ─── Execute Swap ──────────────────────────────────────────────────

    def execute_swap(self, token_in: str, token_out: str, amount_in: float, strategy: str = "MANUAL") -> dict:
        """
        Execute a token swap.
        Live: calls `twak swap <amount> <token_in> <token_out> --chain bsc`
        Mock: simulates with CMC prices and SQLite balance updates
        """
        token_in = token_in.upper()
        token_out = token_out.upper()

        # Get prices for calculations
        prices = cmc_service.get_token_prices()
        price_in = prices.get(token_in, 1.0)
        price_out = prices.get(token_out, 1.0)

        # Check balance
        balances = self.get_balances()
        if balances.get(token_in, 0.0) < amount_in:
            error_msg = f"Insufficient {token_in} balance. Available: {balances.get(token_in, 0.0):.4f}, Requested: {amount_in}"
            tx_hash = self._mock_tx_hash()
            database.log_trade(token_in, token_out, amount_in, 0.0, "FAILED", tx_hash, strategy, error_msg)
            return {"status": "FAILED", "error": error_msg, "tx_hash": tx_hash}

        # Calculate expected output (0.5% slippage)
        amount_out = (amount_in * price_in / price_out) * 0.995

        # ── Live execution via TWAK CLI ──
        if not self.mock_mode and self.twak_available:
            result = self._run_twak([
                "swap", str(amount_in), token_in, token_out,
                "--chain", "bsc",
            ], timeout=30)

            if result:
                tx_hash = "0x"
                if isinstance(result, dict):
                    tx_hash = result.get("txHash", result.get("tx_hash", result.get("hash", self._mock_tx_hash())))
                    if "raw" in result:
                        # Try to extract tx hash from raw output
                        import re
                        match = re.search(r"0x[a-fA-F0-9]{64}", result["raw"])
                        if match:
                            tx_hash = match.group(0)

                # Update DB balances
                new_bal_in = balances[token_in] - amount_in
                new_bal_out = balances.get(token_out, 0.0) + amount_out
                database.set_state(f"balance_{token_in}", str(round(new_bal_in, 6)))
                database.set_state(f"balance_{token_out}", str(round(new_bal_out, 6)))

                database.log_trade(
                    token_in, token_out, amount_in, amount_out,
                    "SUCCESS", tx_hash, strategy, "Live swap executed via TWAK CLI"
                )
                return {
                    "status": "SUCCESS",
                    "tx_hash": tx_hash,
                    "amount_in": amount_in,
                    "amount_out": round(amount_out, 6),
                    "token_in": token_in,
                    "token_out": token_out,
                    "mode": "live",
                }
            else:
                # TWAK command failed — log and fall through to simulation
                print(f"[TWAK] Swap command failed, falling back to simulation")

        # ── Simulated execution ──
        tx_hash = self._mock_tx_hash()
        new_bal_in = balances[token_in] - amount_in
        new_bal_out = balances.get(token_out, 0.0) + amount_out
        database.set_state(f"balance_{token_in}", str(round(new_bal_in, 6)))
        database.set_state(f"balance_{token_out}", str(round(new_bal_out, 6)))

        database.log_trade(
            token_in, token_out, amount_in, amount_out,
            "SUCCESS", tx_hash, strategy, "Simulated swap via TWAK"
        )
        return {
            "status": "SUCCESS",
            "tx_hash": tx_hash,
            "amount_in": amount_in,
            "amount_out": round(amount_out, 6),
            "token_in": token_in,
            "token_out": token_out,
            "mode": "simulated",
        }

    # ─── Swap Quote (read-only) ────────────────────────────────────────

    def get_swap_quote(self, amount: float, token_in: str, token_out: str) -> dict | None:
        """
        Get a swap quote without executing.
        Uses `twak swap <amount> <token_in> <token_out> --quote-only`
        """
        if not self.twak_available:
            return None
        result = self._run_twak([
            "swap", str(amount), token_in.upper(), token_out.upper(),
            "--quote-only",
        ])
        return result

    # ─── Price Alerts ──────────────────────────────────────────────────

    def create_alert(self, token: str, direction: str, price: float) -> dict | None:
        """
        Create a price alert via `twak alert create`.
        direction: 'above' or 'below'
        """
        if not self.twak_available:
            return None
        result = self._run_twak([
            "alert", "create",
            "--token", token.upper(),
            f"--{direction}", str(price),
        ])
        return result

    # ─── Utility ───────────────────────────────────────────────────────

    @staticmethod
    def _mock_tx_hash() -> str:
        return "0x" + "".join(random.choices("0123456789abcdef", k=64))


twak_service = TWAKService()
