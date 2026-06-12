import { useState, useEffect, useRef, useCallback, Component } from 'react'

// ─── Error Boundary (H4) ─────────────────────────────────────────────
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[Sentinel UI] Render error caught by ErrorBoundary:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="app-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ textAlign: 'center', maxWidth: 500 }}>
            <div className="logo-icon" style={{ width: 60, height: 60, fontSize: 20, margin: '0 auto 16px', background: 'none' }}>
              <img src="/logo.png" alt="Sentinel Logo" style={{ width: '100%', height: '100%', borderRadius: 'inherit', objectFit: 'cover' }} />
            </div>
            <h2 style={{ margin: '0 0 12px' }}>Dashboard Error</h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginBottom: 16 }}>
              An unexpected rendering error occurred. This is usually caused by unexpected API data.
            </p>
            <p style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: 'var(--danger-red)', marginBottom: 20 }}>
              {this.state.error?.message || 'Unknown error'}
            </p>
            <button
              className="btn-primary"
              onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload() }}
            >
              Reload Dashboard
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}


function App() {
  const API_BASE = 'http://127.0.0.1:8000'
  const POLL_INTERVAL = 15000 // 15 seconds — backend caches for 15s anyway

  // ─── State ──────────────────────────────────────────────────────────
  const [marketData, setMarketData] = useState(null)
  const [portfolioData, setPortfolioData] = useState(null)
  const [strategySettings, setStrategySettings] = useState({
    strategy: 'BALANCED',
    risk_guard: true,
    target_tokens: ['BNB', 'CAKE', 'USDT'],
  })
  const [strategyStatus, setStrategyStatus] = useState(null)
  const [jobs, setJobs] = useState([])
  const [chatHistory, setChatHistory] = useState([
    {
      sender: 'agent',
      text: "🛡️ **Sentinel Online**\nMonitoring BNB Smart Chain via CoinMarketCap Agent API.\nTrust Wallet execution layer configured.\n\nTry asking me:\n- `what is the market sentiment?`\n- `show my balances`\n- `swap 0.1 BNB to CAKE`\n- `rebalance my wallet`",
    },
  ])
  const [chatInput, setChatInput] = useState('')
  const [backendOnline, setBackendOnline] = useState(false)
  const [loadingAction, setLoadingAction] = useState(false)
  const [initialLoad, setInitialLoad] = useState(true)
  const [twakLive, setTwakLive] = useState(false)

  const chatEndRef = useRef(null)
  const chatHistoryRef = useRef(null)
  const hasUserInteracted = useRef(false)
  const abortControllerRef = useRef(null)

  // ─── Scroll chat container only (not the page) after user interaction
  useEffect(() => {
    if (hasUserInteracted.current && chatHistoryRef.current) {
      const el = chatHistoryRef.current
      el.scrollTop = el.scrollHeight
    }
  }, [chatHistory])

  // Scroll to top on mount
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])

  // ─── Data fetching with AbortController ─────────────────────────────
  const fetchData = useCallback(async () => {
    // Cancel any in-flight requests from the previous poll cycle
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller
    const signal = controller.signal

    try {
      const rootRes = await fetch(`${API_BASE}/`, { signal })
      if (!rootRes.ok) throw new Error('Backend unreachable')

      const rootData = await rootRes.json()
      setBackendOnline(true)
      setTwakLive(rootData.twak_cli === true)

      const [mRes, pRes, sRes, jRes, ssRes] = await Promise.all([
        fetch(`${API_BASE}/api/market`, { signal }),
        fetch(`${API_BASE}/api/portfolio`, { signal }),
        fetch(`${API_BASE}/api/strategy`, { signal }),
        fetch(`${API_BASE}/api/jobs`, { signal }),
        fetch(`${API_BASE}/api/strategy/status`, { signal }),
      ])

      if (mRes.ok) setMarketData(await mRes.json())
      if (pRes.ok) setPortfolioData(await pRes.json())
      if (sRes.ok) setStrategySettings(await sRes.json())
      if (jRes.ok) setJobs(await jRes.json())
      if (ssRes.ok) setStrategyStatus(await ssRes.json())
    } catch (e) {
      if (e.name === 'AbortError') return // Expected when a new poll cancels the old one
      setBackendOnline(false)
      console.warn('Backend offline:', e.message)
    } finally {
      setInitialLoad(false)
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchData()
    const interval = setInterval(fetchData, POLL_INTERVAL)
    return () => {
      clearInterval(interval)
      if (abortControllerRef.current) abortControllerRef.current.abort()
    }
  }, [fetchData])

  // ─── Chat ───────────────────────────────────────────────────────────
  const sendMessage = async (e) => {
    if (e) e.preventDefault()
    if (!chatInput.trim()) return

    hasUserInteracted.current = true
    const userMessage = chatInput.trim()
    setChatHistory((prev) => [...prev, { sender: 'user', text: userMessage }])
    setChatInput('')
    setLoadingAction(true)

    setChatHistory((prev) => [...prev, { sender: 'agent', text: '⏳ Thinking...' }])

    try {
      if (backendOnline) {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: userMessage }),
        })
        if (res.ok) {
          const data = await res.json()
          setChatHistory((prev) => {
            const copy = [...prev]
            copy[copy.length - 1] = { sender: 'agent', text: data.response }
            return copy
          })
          // Refresh portfolio after action
          try {
            const pRes = await fetch(`${API_BASE}/api/portfolio`)
            if (pRes.ok) setPortfolioData(await pRes.json())
          } catch { /* non-critical */ }
        } else {
          updateLastAgentMsg('⚠️ Backend returned an error. Check the server logs.')
        }
      } else {
        handleLocalChatSimulation(userMessage)
      }
    } catch {
      updateLastAgentMsg('⚠️ Error communicating with the Sentinel backend.')
    } finally {
      setLoadingAction(false)
    }
  }

  const updateLastAgentMsg = (text) => {
    setChatHistory((prev) => {
      const copy = [...prev]
      copy[copy.length - 1] = { sender: 'agent', text }
      return copy
    })
  }

  const handleLocalChatSimulation = (msg) => {
    const text = msg.toLowerCase()
    let response;
    if (text.includes('swap') || text.includes('buy') || text.includes('sell')) {
      response = "⚡ **Swap requires backend**\nStart the backend with:\n`cd backend && python main.py`"
    } else if (['sentiment', 'market', 'fear', 'greed'].some((k) => text.includes(k))) {
      response = "📊 **Market data requires backend**\nThe CoinMarketCap Agent API is accessed through the Python backend."
    } else if (['balance', 'portfolio', 'wallet'].some((k) => text.includes(k))) {
      response = "💼 **Portfolio data requires backend**\nStart: `cd backend && python main.py`"
    } else {
      response = "I'm in offline mode. Start the backend at `localhost:8000` for full functionality."
    }
    updateLastAgentMsg(response)
  }

  // ─── Strategy controls ──────────────────────────────────────────────
  const handleStrategyChange = async (newStrategy) => {
    const updated = { ...strategySettings, strategy: newStrategy }
    setStrategySettings(updated)
    if (backendOnline) {
      try {
        await fetch(`${API_BASE}/api/strategy`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ strategy: newStrategy, risk_guard: strategySettings.risk_guard }),
        })
      } catch (e) {
        console.error('Failed to update strategy settings:', e)
      }
    }
  }

  const handleRiskGuardToggle = async () => {
    const updated = { ...strategySettings, risk_guard: !strategySettings.risk_guard }
    setStrategySettings(updated)
    if (backendOnline) {
      try {
        await fetch(`${API_BASE}/api/strategy`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ strategy: strategySettings.strategy, risk_guard: !strategySettings.risk_guard }),
        })
      } catch (e) {
        console.error('Failed to toggle risk guard:', e)
      }
    }
  }

  // ─── Mock job trigger ───────────────────────────────────────────────
  const triggerMockJob = async () => {
    const descs = [
      'Rebalance portfolio to USDT stablecoins — market overheating',
      'DCA purchase of CAKE at support levels',
      'Rotate CAKE to BNB to capture gas fee incentives',
      'Risk-hedge: swap 5% CAKE → USDT',
    ]
    const desc = descs[Math.floor(Math.random() * descs.length)]

    if (backendOnline) {
      try {
        await fetch(`${API_BASE}/api/jobs`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ description: desc, budget: 0.05 }),
        })
        const jRes = await fetch(`${API_BASE}/api/jobs`)
        if (jRes.ok) setJobs(await jRes.json())
      } catch (e) {
        console.error('Failed to create mock client job:', e)
      }
    } else {
      const newJob = {
        id: 'job-' + Math.random().toString(36).substr(2, 6),
        client: '0x' + Math.random().toString(16).substr(2, 40),
        description: desc,
        budget: 0.05,
        status: 'FUNDED',
        deliverable: null,
        created_at: new Date().toISOString(),
      }
      setJobs((prev) => [newJob, ...prev])
      setTimeout(() => setJobs((prev) => prev.map((j) => (j.id === newJob.id ? { ...j, status: 'EXECUTING' } : j))), 3000)
      setTimeout(() => setJobs((prev) => prev.map((j) => (j.id === newJob.id ? { ...j, status: 'DELIVERED', deliverable: 'https://ipfs.io/ipfs/QmMockReceipt' } : j))), 7000)
      setTimeout(() => setJobs((prev) => prev.map((j) => (j.id === newJob.id ? { ...j, status: 'SETTLED' } : j))), 12000)
    }
  }

  // ─── Helpers (null-safe) ───────────────────────────────────────────
  const fg = marketData?.fear_greed || { value: 0, classification: 'Loading...' }
  const prices = marketData?.prices || {}
  const trends = marketData?.trends || []
  const funding = marketData?.funding_rates || {}
  const balances = portfolioData?.balances || { BNB: 0, CAKE: 0, USDT: 0 }
  const identity = portfolioData?.identity || { token_id: '—', agent_wallet: '—', mode: '—' }
  const recentTrades = portfolioData?.recent_trades || []
  const estimatedUsd = portfolioData?.estimated_usd_value || 0

  const bnbValue = (balances.BNB || 0) * (prices.BNB || 0)
  const cakeValue = (balances.CAKE || 0) * (prices.CAKE || 0)
  const usdtValue = balances.USDT || 0
  const totalVal = bnbValue + cakeValue + usdtValue
  const bnbPct = totalVal > 0 ? (bnbValue / totalVal) * 100 : 0
  const cakePct = totalVal > 0 ? (cakeValue / totalVal) * 100 : 0
  const usdtPct = totalVal > 0 ? (usdtValue / totalVal) * 100 : 0

  // Safe number formatting helper
  const safeFixed = (val, digits = 2) => {
    const n = Number(val)
    return isNaN(n) ? '0' : n.toFixed(digits)
  }

  // Safe text render (no dangerouslySetInnerHTML)
  const renderChatText = (text) => {
    if (!text) return null
    const parts = text.split(/(\*\*.*?\*\*|`.*?`|\n)/g)
    return parts.map((part, i) => {
      if (!part) return null
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i}>{part.slice(2, -2)}</strong>
      }
      if (part.startsWith('`') && part.endsWith('`')) {
        return <code key={i}>{part.slice(1, -1)}</code>
      }
      if (part === '\n') return <br key={i} />
      return <span key={i}>{part}</span>
    })
  }

  const fgTagClass = () => {
    const cls = (fg.classification || '').toLowerCase()
    if (cls.includes('extreme greed')) return 'extreme-greed'
    if (cls.includes('greed')) return 'greed'
    if (cls.includes('extreme fear')) return 'extreme-fear'
    if (cls.includes('fear')) return 'fear'
    return 'neutral'
  }

  // Strategy loop health indicator
  const loopHealthBadge = () => {
    if (!strategyStatus) return null
    const health = strategyStatus.loop_health || 'UNKNOWN'
    let color = 'var(--text-muted)'
    if (health === 'MONITORING') color = 'var(--success-green)'
    else if (health.startsWith('ERROR')) color = 'var(--danger-red)'
    else if (health === 'COOLDOWN_ACTIVE') color = 'var(--warning-orange)'
    else if (health === 'IDLE_GUARD_OFF') color = 'var(--text-secondary)'
    return (
      <span style={{ fontSize: 11, color, fontWeight: 600, marginLeft: 8 }}>
        ● {health}
      </span>
    )
  }

  // ─── Loading Screen ─────────────────────────────────────────────────
  if (initialLoad) {
    return (
      <div className="app-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <div className="logo-icon" style={{ width: 60, height: 60, fontSize: 20, margin: '0 auto 16px', background: 'none' }}>
            <img src="/logo.png" alt="Sentinel Logo" style={{ width: '100%', height: '100%', borderRadius: 'inherit', objectFit: 'cover' }} />
          </div>
          <h2 style={{ margin: 0 }}>SENTINEL</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>Connecting to backend...</p>
        </div>
      </div>
    )
  }

  // ─── Render ─────────────────────────────────────────────────────────
  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="logo-section">
          <div className="logo-icon" style={{ background: 'none' }}>
            <img src="/logo.png" alt="Sentinel Logo" style={{ width: '100%', height: '100%', borderRadius: 'inherit', objectFit: 'cover' }} />
          </div>
          <div className="logo-text">
            <h1>SENTINEL</h1>
            <span>BSC Sentiment Strategy Agent</span>
          </div>
        </div>
        <div className="header-status">
          <div className={`badge ${backendOnline ? 'badge-active' : ''}`}>
            <span
              className={backendOnline ? 'status-dot' : ''}
              style={!backendOnline ? { width: 8, height: 8, borderRadius: '50%', background: '#f6465d', display: 'inline-block' } : undefined}
            />
            {backendOnline ? 'SENTINEL NODE LIVE' : 'NODE OFFLINE'}
          </div>
          {twakLive && <div className="badge badge-active">TWAK CLI ✓</div>}
          <div className="badge badge-gold">ERC-8004 ID: {identity.token_id}</div>
        </div>
      </header>

      {/* Dashboard Grid */}
      <div className="dashboard-grid">
        {/* ── Left Column ── */}
        <div className="column">
          {/* Market Radar */}
          <div className="glass-panel card-content">
            <div className="card-title">
              <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M21 12c0-4.97-4.03-9-9-9s-9 4.03-9 9 4.03 9 9 9 9-4.03 9-9Z" /><path d="M12 7v5l3 3" /></svg>
                Market Intelligence Radar
              </h2>
              <span className="badge">
                {fg.source === 'coinmarketcap_trial_pro' ? '🟢 CMC Live' : fg.source === 'coinmarketcap_pro' ? '🟢 CMC Pro' : '🟡 Cached'}
              </span>
            </div>

            <div className="sentiment-display">
              <div className="sentiment-gauge">
                <span className="value">{marketData ? Math.round(fg.value ?? 0) : '—'}</span>
                <span className="label">Fear & Greed Index</span>
              </div>
              <div className={`sentiment-tag ${fgTagClass()}`}>
                {fg.classification || 'Loading...'}
              </div>
            </div>

            <div className="price-grid">
              {['BNB', 'CAKE', 'BTC', 'ETH'].map((sym) => (
                <div className="price-card" key={sym}>
                  <div className="symbol">{sym}</div>
                  <div className="value">
                    {prices[sym] ? `$${prices[sym] < 1 ? safeFixed(prices[sym], 4) : Number(prices[sym]).toLocaleString('en-US', { maximumFractionDigits: 2 })}` : '—'}
                  </div>
                </div>
              ))}
            </div>

            <h3 style={{ fontSize: 13, textTransform: 'uppercase', color: 'var(--text-secondary)', letterSpacing: 1, margin: '20px 0 10px' }}>
              Trending Assets
            </h3>
            <table className="data-table">
              <thead>
                <tr><th>Asset</th><th>Price</th><th>24h Change</th><th>Vol Change</th></tr>
              </thead>
              <tbody>
                {trends.length > 0 ? trends.slice(0, 6).map((t, idx) => (
                  <tr key={idx}>
                    <td style={{ fontWeight: 600 }}>{t.name || '—'} ({t.symbol || '?'})</td>
                    <td>${(t.price ?? 0) < 1 ? safeFixed(t.price ?? 0, 6) : safeFixed(t.price ?? 0, 2)}</td>
                    <td className={(t.change_24h ?? 0) >= 0 ? 'change-up' : 'change-down'}>
                      {(t.change_24h ?? 0) >= 0 ? '+' : ''}{safeFixed(t.change_24h ?? 0, 2)}%
                    </td>
                    <td className={(t.volume_change_24h ?? 0) >= 0 ? 'change-up' : 'change-down'}>
                      {(t.volume_change_24h ?? 0) >= 0 ? '▲' : '▼'} {safeFixed(Math.abs(t.volume_change_24h ?? 0), 2)}%
                    </td>
                  </tr>
                )) : (
                  <tr><td colSpan="4" style={{ textAlign: 'center', padding: '16px 0', color: 'var(--text-muted)' }}>Waiting for data...</td></tr>
                )}
              </tbody>
            </table>

            {/* Funding Rates */}
            {Object.keys(funding).length > 0 && (
              <>
                <h3 style={{ fontSize: 13, textTransform: 'uppercase', color: 'var(--text-secondary)', letterSpacing: 1, margin: '20px 0 10px' }}>
                  Perpetual Funding Rates
                </h3>
                <div className="price-grid">
                  {Object.entries(funding).map(([label, rate]) => (
                    <div className="price-card" key={label}>
                      <div className="symbol">{label}</div>
                      <div className="value" style={{ color: (rate ?? 0) >= 0 ? 'var(--success-green)' : 'var(--danger-red)' }}>
                        {safeFixed((rate ?? 0) * 100, 4)}%
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Strategy Control */}
          <div className="glass-panel card-content">
            <div className="card-title">
              <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
                Autonomous Strategy Settings
                {loopHealthBadge()}
              </h2>
            </div>
            <div className="strategy-form">
              <div className="strategy-select-container">
                <label>Target Portfolio Mode</label>
                <select id="strategy-mode-select" className="select-input" value={strategySettings.strategy} onChange={(e) => handleStrategyChange(e.target.value)}>
                  <option value="BALANCED">Balanced (40% BNB, 20% CAKE, 40% USDT)</option>
                  <option value="CONSERVATIVE">Conservative (30% BNB, 10% CAKE, 60% USDT)</option>
                  <option value="AGGRESSIVE">Aggressive (50% BNB, 40% CAKE, 10% USDT)</option>
                </select>
              </div>
              <div className="toggle-container">
                <div className="toggle-label">
                  <span>Sentiment Risk Guard</span>
                  <small>Auto-rotates to USDT when Fear &amp; Greed &gt; 78 (Extreme Greed)</small>
                </div>
                <label className="switch">
                  <input id="risk-guard-toggle" type="checkbox" checked={strategySettings.risk_guard} onChange={handleRiskGuardToggle} />
                  <span className="slider" />
                </label>
              </div>
              {strategyStatus?.last_action && (
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', borderTop: '1px solid var(--border-color)', paddingTop: 10, marginTop: 4 }}>
                  Last action: <strong style={{ color: 'var(--text-primary)' }}>{strategyStatus.last_action}</strong>
                  {strategyStatus.last_action_time && (
                    <span style={{ marginLeft: 8 }}>
                      at {new Date(strategyStatus.last_action_time).toLocaleTimeString()}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ERC-8183 Commerce Hub */}
          <div className="glass-panel card-content">
            <div className="commerce-header">
              <div className="card-title" style={{ margin: 0, border: 'none', padding: 0 }}>
                <h2>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
                  ERC-8183 Merchant Commerce
                </h2>
              </div>
              <button id="fund-escrow-job-btn" className="btn-secondary" onClick={triggerMockJob}>+ Fund Escrow Job</button>
            </div>

            <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 0, marginBottom: 15 }}>
              On-chain escrow allows clients to hire the Sentinel for autonomous tasks. Payment settles automatically after the dispute window.
            </p>

            <div className="job-list">
              {jobs.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '20px 0', fontSize: 13, color: 'var(--text-muted)' }}>
                  No active commerce jobs
                </div>
              ) : (
                jobs.map((job) => (
                  <div key={job.id} className="job-card">
                    <div className="job-meta">
                      <span className="job-id">{job.id}</span>
                      <span className="job-budget">{job.budget} BNB</span>
                    </div>
                    <div className="job-desc">{job.description}</div>
                    <div className="job-status-line">
                      <span className="client-addr" style={{ color: 'var(--text-muted)' }}>
                        Client: {job.client?.slice(0, 6)}...{job.client?.slice(-4)}
                      </span>
                      <span>
                        Status: <span className={`status-txt ${(job.status || '').toLowerCase()}`}>{job.status}</span>
                      </span>
                    </div>
                    {job.deliverable && (
                      <div style={{ marginTop: 8, fontSize: 11, borderTop: '1px solid rgba(255,255,255,0.03)', paddingTop: 6 }}>
                        🔗 Receipt: <a href={job.deliverable} target="_blank" rel="noopener noreferrer" className="deliverable-link">{job.deliverable.slice(0, 45)}...</a>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* ── Right Column ── */}
        <div className="column">
          {/* Trust Wallet Panel */}
          <div className="glass-panel card-content">
            <div className="card-title">
              <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="2" y="4" width="20" height="16" rx="2" ry="2" /><path d="M12 4v16M2 10h20" /></svg>
                Trust Wallet Execution Layer (TWAK)
              </h2>
              <span className={`badge ${twakLive ? 'badge-active' : 'badge-gold'}`}>
                {twakLive ? '🟢 Live CLI' : identity.mode === 'simulated' ? '🟡 Simulated' : '🟢 Live'}
              </span>
            </div>

            <div className="portfolio-value">
              <div className="title">Estimated Scoped Balance</div>
              <div className="amount">
                ${Number(estimatedUsd || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'JetBrains Mono', marginTop: 4 }}>
                Wallet: {identity.agent_wallet}
              </div>
            </div>

            <div className="asset-bars">
              {[
                { token: 'BNB', bal: balances.BNB || 0, pct: bnbPct, cls: 'bnb' },
                { token: 'CAKE', bal: balances.CAKE || 0, pct: cakePct, cls: 'cake' },
                { token: 'USDT', bal: balances.USDT || 0, pct: usdtPct, cls: 'usdt' },
              ].map(({ token, bal, pct, cls }) => (
                <div className="asset-row" key={token}>
                  <div className="asset-info"><span className="asset-token">{token}</span></div>
                  <div className="asset-progress-container">
                    <div className={`asset-progress-bar ${cls}`} style={{ width: `${pct}%`, transition: 'width 0.6s ease' }} />
                  </div>
                  <div className="asset-bal">
                    <div className="qty">{safeFixed(bal, token === 'BNB' ? 4 : 2)}</div>
                    <div className="usd">${safeFixed(bal * (prices[token] || 1), 2)}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Chat Copilot */}
          <div className="glass-panel card-content" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="card-title" style={{ margin: 0 }}>
              <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
                Sentinel NLP Copilot
              </h2>
            </div>

            <div className="chat-container">
              <div className="chat-history" ref={chatHistoryRef}>
                {chatHistory.map((msg, index) => (
                  <div key={index} className={`message-bubble ${msg.sender === 'user' ? 'message-user' : 'message-agent'}`}>
                    {renderChatText(msg.text)}
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>

              <form className="chat-input-area" onSubmit={sendMessage}>
                <input
                  id="chat-copilot-input"
                  type="text"
                  className="chat-input"
                  placeholder="Ask for sentiment, request swap, or rebalance..."
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      e.stopPropagation()
                      sendMessage()
                    }
                  }}
                  disabled={loadingAction}
                />
                <button id="chat-send-btn" type="submit" className="btn-primary" disabled={loadingAction}>
                  Send
                </button>
              </form>
            </div>
          </div>

          {/* Trade Ledger */}
          <div className="glass-panel card-content">
            <div className="card-title">
              <h2>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 20h9M5 20h.01M19 16V4a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v16M9 8h4M9 12h4" /></svg>
                Execution Trade Ledger
              </h2>
            </div>
            <table className="data-table" style={{ fontSize: 13 }}>
              <thead>
                <tr><th>Time</th><th>Trade</th><th>Amount</th><th>Tx Hash</th><th>Status</th></tr>
              </thead>
              <tbody>
                {recentTrades.length === 0 ? (
                  <tr><td colSpan="5" style={{ textAlign: 'center', padding: '20px 0', color: 'var(--text-muted)' }}>No swap executions recorded</td></tr>
                ) : (
                  recentTrades.map((t) => (
                    <tr key={t.id}>
                      <td style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {t.timestamp ? new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'}
                      </td>
                      <td style={{ fontWeight: 600 }}>{t.token_in || '?'} → {t.token_out || '?'}</td>
                      <td>{safeFixed(t.amount_in, 3)}</td>
                      <td style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: 'var(--accent-cyan)' }}>
                        <a href={`https://bscscan.com/tx/${t.tx_hash}`} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                          {(t.tx_hash || '').slice(0, 10)}...
                        </a>
                      </td>
                      <td>
                        <span style={{ color: t.status === 'SUCCESS' ? 'var(--success-green)' : 'var(--danger-red)', fontWeight: 700 }}>
                          {t.status || '—'}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

function AppWithBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  )
}

export default AppWithBoundary
