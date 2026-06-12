"""
BNB Agent SDK Commerce Service (ERC-8004 / ERC-8183)
=====================================================
Handles on-chain agent identity registration (ERC-8004) and
agentic commerce / escrow job lifecycle (ERC-8183).

SDK Repo: https://github.com/bnb-chain/bnbagent-sdk
"""

import threading
import time
import random
import uuid
from config import settings
import database
from services.twak import twak_service

# ── BNB Agent SDK import ──
BNB_AGENT_SDK_AVAILABLE = False
_create_erc8183_app = None
_register_agent = None

try:
    from bnbagent.erc8183.server import create_erc8183_app as _create_fn
    _create_erc8183_app = _create_fn
    BNB_AGENT_SDK_AVAILABLE = True
    print("[Commerce] ✓ bnbagent SDK loaded — ERC-8183 server available")
except ImportError:
    pass

try:
    from bnbagent.erc8004.registry import register_agent as _reg_fn
    _register_agent = _reg_fn
    if not BNB_AGENT_SDK_AVAILABLE:
        BNB_AGENT_SDK_AVAILABLE = True
    print("[Commerce] ✓ bnbagent SDK loaded — ERC-8004 registry available")
except ImportError:
    pass

if not BNB_AGENT_SDK_AVAILABLE:
    print("[Commerce] ⚠ bnbagent SDK not installed — using simulated agentic commerce")
    print("[Commerce]   Install: pip install bnbagent")


class CommerceService:
    def __init__(self):
        self.mock_mode = settings.MOCK_MODE or not BNB_AGENT_SDK_AVAILABLE
        self.service_price = settings.AGENT_SERVICE_PRICE
        self.dispute_window = settings.AGENT_DISPUTE_WINDOW_SECONDS

        # Cache identity registration
        self._identity_cache = None

        # Start simulated job engine in background
        if self.mock_mode:
            t = threading.Thread(target=self._run_simulated_polling, daemon=True)
            t.start()

    # ─── ERC-8004: Agent Identity ──────────────────────────────────────

    def register_identity(self) -> dict:
        """
        Register the agent's on-chain identity via ERC-8004.
        Live mode: Uses bnbagent SDK to register on BSC.
        Mock mode: Returns a deterministic simulated identity.
        """
        # Return cached if available
        if self._identity_cache:
            return self._identity_cache

        # ── Live: Use bnbagent SDK ──
        if not self.mock_mode and _register_agent is not None:
            try:
                result = _register_agent(
                    private_key=settings.AGENT_PRIVATE_KEY,
                    rpc_url=settings.RPC_URL,
                    registry_contract=settings.ERC8004_REGISTRY_ADDR,
                )
                if result:
                    identity = {
                        "status": "REGISTERED",
                        "agent_id": result.get("agent_id", f"agent-sentinel-{settings.ERC8004_REGISTRY_ADDR[-6:]}"),
                        "token_id": result.get("token_id", 0),
                        "registry_contract": settings.ERC8004_REGISTRY_ADDR,
                        "agent_wallet": result.get("wallet", result.get("address", "")),
                        "mode": "live",
                    }
                    self._identity_cache = identity
                    print(f"[Commerce] ✓ Agent registered on-chain: token_id={identity['token_id']}")
                    return identity
            except Exception as e:
                print(f"[Commerce] ERC-8004 registration failed: {e}")
                print("[Commerce]   Falling back to simulated identity")

        # ── Simulated identity ──
        # Deterministic so it doesn't change on every call
        agent_id = f"agent-sentinel-{settings.ERC8004_REGISTRY_ADDR[-6:]}"
        # Derive the actual public address from the private key safely
        agent_wallet = "0xE938c93f5f891D5B9411249B3684a29475824bF2"  # Sane default
        try:
            from eth_account import Account
            pk = settings.AGENT_PRIVATE_KEY.strip()
            if not pk.startswith("0x"):
                pk = "0x" + pk
            acct = Account.from_key(pk)
            agent_wallet = acct.address
        except Exception as e:
            print(f"[Commerce] Failed to derive public wallet address: {e}")

        identity = {
            "status": "REGISTERED",
            "agent_id": agent_id,
            "token_id": 4022026,
            "registry_contract": settings.ERC8004_REGISTRY_ADDR,
            "agent_wallet": agent_wallet,
            "mode": "simulated",
        }
        self._identity_cache = identity
        return identity

    # ─── ERC-8183: Job Management ──────────────────────────────────────

    def trigger_mock_client_job(self, description: str, budget: float) -> str:
        """Simulate a client creating and funding an escrow job on-chain."""
        job_id = "job-" + str(uuid.uuid4())[:8]
        client_address = "0x" + "".join(random.choices("0123456789abcdef", k=40))
        database.insert_job(job_id, client_address, description, budget, "FUNDED")
        return job_id

    # ─── Background Job Poller ─────────────────────────────────────────

    def _run_simulated_polling(self):
        """
        Background worker that polls the DB for FUNDED jobs,
        executes them via TWAK, submits a deliverable receipt,
        and transitions to SETTLED after the dispute window (timestamp-based, non-blocking).
        """
        print("[Commerce] Starting job polling loop...")
        while True:
            try:
                time.sleep(3)
                jobs = database.get_jobs(limit=10)
                for job in jobs:
                    job_id = job["id"]
                    status = job["status"]
                    description = job["description"].lower()

                    if status == "FUNDED":
                        print(f"[Commerce] Found funded job: {job_id}. Executing...")
                        database.update_job_status(job_id, "EXECUTING")

                        # Simulate execution delay
                        time.sleep(2)

                        # Interpret job description and execute
                        token_in, token_out, amount = "BNB", "USDT", 0.05
                        if "cake" in description:
                            token_in, token_out = "BNB", "CAKE"
                        elif "stable" in description or "usdt" in description:
                            token_in, token_out = "BNB", "USDT"
                        elif "rebalance" in description or "rotate" in description:
                            token_in, token_out = "CAKE", "USDT"
                            amount = 10.0

                        # Execute swap via TWAK service (live or simulated)
                        result = twak_service.execute_swap(token_in, token_out, amount, strategy="COMMERCE_JOB")

                        if result["status"] == "SUCCESS":
                            deliverable_url = (
                                f"https://ipfs.io/ipfs/QmReceipt{job_id[-4:]}"
                                f"tx{result['tx_hash'][:10]}"
                            )
                            database.update_job_status(job_id, "DELIVERED", deliverable_url)
                            print(f"[Commerce] Job {job_id} DELIVERED — {deliverable_url}")
                        else:
                            database.update_job_status(job_id, "STALEMATE")
                            print(f"[Commerce] Job {job_id} failed: {result.get('error')}")

                    elif status == "DELIVERED":
                        # Check if dispute window has elapsed (non-blocking)
                        created_at = job.get("created_at", "")
                        try:
                            from datetime import datetime, timezone
                            job_time = datetime.fromisoformat(created_at.rstrip("Z")).replace(tzinfo=timezone.utc)
                            elapsed = (datetime.now(timezone.utc) - job_time).total_seconds()
                        except (ValueError, TypeError):
                            elapsed = self.dispute_window + 1  # settle immediately if timestamp is invalid

                        if elapsed >= self.dispute_window:
                            database.update_job_status(job_id, "SETTLED", settled=True)

                            # Credit agent fee
                            current_bnb = float(database.get_state("balance_BNB", "10.0"))
                            database.set_state("balance_BNB", str(round(current_bnb + job["budget"], 4)))
                            print(f"[Commerce] Job {job_id} SETTLED — agent earned {job['budget']} BNB")

            except Exception as e:
                print(f"[Commerce] Polling error: {e}")

    # ─── ERC-8183: Mount Live FastAPI Sub-App ──────────────────────────

    def mount_live_app(self, main_fastapi_app):
        """
        Mount the real ERC-8183 commerce server as a FastAPI sub-app.
        Only works when bnbagent SDK is installed and mock mode is off.
        """
        if self.mock_mode or _create_erc8183_app is None:
            print("[Commerce] Mock mode — skipping ERC-8183 server mount")
            return

        try:
            def on_job_received(job_data):
                job_id = job_data.get("jobId", f"job-{uuid.uuid4().hex[:8]}")
                client = job_data.get("client", "0x" + "0" * 40)
                desc = job_data.get("description", "")
                budget = float(job_data.get("budget", 0.0))

                database.insert_job(job_id, client, desc, budget, "FUNDED")
                print(f"[Commerce] ✓ Live job received: {job_id} from {client[:10]}...")

                # Execute job synchronously to avoid premature delivery
                token_in, token_out, amount = "BNB", "USDT", 0.05
                if "cake" in desc.lower():
                    token_in, token_out = "BNB", "CAKE"
                elif "stable" in desc.lower() or "usdt" in desc.lower():
                    token_in, token_out = "BNB", "USDT"
                elif "rebalance" in desc.lower() or "rotate" in desc.lower():
                    token_in, token_out = "CAKE", "USDT"
                    amount = 10.0

                database.update_job_status(job_id, "EXECUTING")
                result = twak_service.execute_swap(token_in, token_out, amount, strategy="COMMERCE_JOB")

                if result["status"] == "SUCCESS":
                    deliverable_url = f"https://ipfs.io/ipfs/QmReceipt{job_id[-4:]}tx{result['tx_hash'][:10]}"
                    database.update_job_status(job_id, "DELIVERED", deliverable_url)
                    return deliverable_url
                else:
                    database.update_job_status(job_id, "STALEMATE")
                    raise Exception(f"Job execution failed: {result.get('error')}")

            commerce_app = _create_erc8183_app(
                on_job=on_job_received,
                private_key=settings.AGENT_PRIVATE_KEY,
                rpc_url=settings.RPC_URL,
                commerce_contract=settings.ERC8183_COMMERCE_ADDR,
            )
            main_fastapi_app.mount("/erc8183", commerce_app)
            print("[Commerce] ✓ Live ERC-8183 sub-app mounted at /erc8183")
        except Exception as e:
            print(f"[Commerce] Failed to mount ERC-8183: {e}")


commerce_service = CommerceService()
