# 🛡️ BNB Sentiment Sentinel

**Autonomous Portfolio Manager & Risk Guard for BNB Smart Chain**

An AI-powered trading agent that reads crypto markets via CoinMarketCap, makes autonomous portfolio decisions based on sentiment analysis, and executes on-chain via Trust Wallet Agent Kit — all on the BNB Smart Chain.

> Built for **BNB Hack: AI Trading Agent Edition** (Track 1 — Autonomous Trading Agents)

---

## 🏗️ Architecture

```
┌──────────────────────┐     ┌───────────────────────────────┐
│   React + Vite UI    │────▶│   FastAPI Backend (:8000)      │
│   Dashboard (:5173)  │◀────│                               │
└──────────────────────┘     │  ┌─────────────────────────┐  │
                             │  │ CMC Agent API Service    │──│──▶ CoinMarketCap Trial Pro API
                             │  │ (Fear & Greed, prices,   │  │
                             │  │  trends, funding rates)  │  │
                             │  └─────────────────────────┘  │
                             │  ┌─────────────────────────┐  │
                             │  │ TWAK Service             │──│──▶ Trust Wallet Agent Kit CLI
                             │  │ (swap, portfolio,        │  │    (on-chain execution)
                             │  │  price alerts)           │  │
                             │  └─────────────────────────┘  │
                             │  ┌─────────────────────────┐  │
                             │  │ Commerce Service         │──│──▶ BNB Agent SDK
                             │  │ (ERC-8004 identity,      │  │    (ERC-8004 / ERC-8183)
                             │  │  ERC-8183 escrow jobs)   │  │
                             │  └─────────────────────────┘  │
                             │  ┌─────────────────────────┐  │
                             │  │ SQLite DB                │  │
                             │  │ (trades, jobs, state)    │  │
                             │  └─────────────────────────┘  │
                             │  ┌─────────────────────────┐  │
                             │  │ Autonomous Strategy Loop │  │
                             │  │ (60s interval, auto-     │  │
                             │  │  rebalance on sentiment) │  │
                             │  └─────────────────────────┘  │
                             └───────────────────────────────┘
```

## ✨ Features

- **📊 Live Market Intelligence** — Real-time Fear & Greed Index, token prices, trending assets, and perpetual funding rates via the CoinMarketCap Agent API (Trial Pro, keyless)
- **💱 On-Chain Execution** — Token swaps, portfolio queries, and price alerts via Trust Wallet Agent Kit (TWAK) CLI
- **🤖 Autonomous Strategy Loop** — Background thread monitors sentiment every 60 seconds:
  - **Risk Guard**: Auto-rotates 20% of non-USDT holdings to stablecoins when Extreme Greed (>78)
  - **DCA Accumulation**: Dollar-cost averages into BNB/CAKE during Extreme Fear (<25)
- **🛡️ On-Chain Agent Identity** — ERC-8004 agent registration on BSC via `bnbagent-sdk`
- **💼 Agentic Commerce** — ERC-8183 escrow-based job system: clients fund jobs, the agent executes and settles automatically
- **💬 NLP Copilot** — Natural-language interface for swaps, rebalancing, sentiment queries, and portfolio checks
- **🎨 Premium Dashboard** — Glassmorphism-styled React dashboard with live data indicators

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+** and **Node.js 18+**
- (Optional) [Trust Wallet Agent Kit](https://portal.trustwallet.com/) for live on-chain execution
- (Optional) [bnbagent SDK](https://github.com/bnb-chain/bnbagent-sdk) for ERC-8004/8183

### 1. Backend Setup

```bash
cd backend
cp .env.example .env          # Edit with your keys (optional — works in mock mode)
pip install -r requirements.txt
python main.py                # Starts on http://127.0.0.1:8000
```

### 2. Frontend Setup

```bash
npm install
npm run dev                   # Starts on http://localhost:5173
```

### 3. (Optional) Install TWAK CLI

```bash
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
# Follow prompts to enter your Access ID and HMAC Secret
# Get credentials at: https://portal.trustwallet.com/dashboard/apps
```

## 🔧 Configuration

All configuration is via environment variables (see `backend/.env.example`):

| Variable | Description | Default |
|---|---|---|
| `MOCK_MODE` | Simulate trades without on-chain execution | `True` |
| `CMC_API_KEY` | CoinMarketCap Pro API key (optional — Trial Pro is keyless) | Mock |
| `TWAK_ACCESS_ID` | Trust Wallet Agent Kit Access ID | Mock |
| `TWAK_HMAC_SECRET` | Trust Wallet Agent Kit HMAC Secret | Mock |
| `AGENT_PRIVATE_KEY` | BSC wallet private key for agent identity | Mock |
| `RPC_URL` | BSC RPC endpoint | BSC Testnet |

## 📡 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Server health & status |
| `GET` | `/api/market` | Fear & Greed, prices, trends, funding rates |
| `GET` | `/api/portfolio` | Wallet balances, identity, trade history |
| `GET` | `/api/strategy` | Current strategy settings |
| `POST` | `/api/strategy` | Update strategy & risk guard |
| `GET` | `/api/jobs` | ERC-8183 commerce job list |
| `POST` | `/api/jobs` | Fund a new escrow job |
| `POST` | `/api/chat` | NLP copilot interface |

## 🏆 Competition Integration

| Technology | Usage |
|---|---|
| **CoinMarketCap Agent API** | All market data (F&G, quotes, trending) via Trial Pro API |
| **Trust Wallet Agent Kit** | On-chain swap execution, wallet portfolio, price alerts via CLI |
| **BNB AI Agent SDK** | ERC-8004 identity registration, ERC-8183 commerce server |

## 📜 License

MIT
