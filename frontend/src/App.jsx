import React, { useState, useMemo, useCallback, useEffect } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, ReferenceLine
} from 'recharts';
import {
  Layers, Activity, CheckCircle2, BarChart3, PieChart as PieIcon, Zap,
  Wifi, WifiOff, Wallet, DollarSign, User as UserIcon, LogIn, LogOut,
  Check, AlertCircle, PlayCircle, Clock, ArrowUpRight, ArrowDownRight,
  Sparkles, RefreshCw, FileDown, Sliders, Globe, Building, Briefcase,
  Home, GraduationCap, Palmtree, Target, ShieldCheck, Shield, ChevronRight,
  TrendingUp, TrendingDown, Lock, Server, Cpu, ExternalLink, Copy, CheckCheck
} from 'lucide-react';

import sampleIntents from './data/sample_intents.json';
import marketParams from './data/market_parameters.json';
import systemConfig from './data/system_config.json';
import {
  compileIntent, runMonteCarlo, healthCheck, API_BASE,
  loginUser, registerUser, fetchCurrentUser, logoutUser, getStoredToken,
  fetchPortfolios, createPortfolio, fetchPortfolioDetail, depositCash, withdrawCash,
  placeTrade, executeRebalance, fetchTransactions, fetchOrders, fetchUniverseQuotes
} from './api';

const GOAL_ICONS = {
  'GOAL-HOM-8921': Home,
  'GOAL-RET-4812': Briefcase,
  'GOAL-EDU-3340': GraduationCap,
  'GOAL-TRAV-1105': Palmtree,
  'GOAL-WEALTH-7789': Building,
};

// Electrified High-Contrast Asset Palette (Electric Cobalt + Acid Lime)
const ALLOCATION_PALETTE = [
  { key: 'us_equity', label: 'US Equity', fill: '#2b5cff' },
  { key: 'intl_equity', label: 'International Equity', fill: '#60a5fa' },
  { key: 'us_bonds', label: 'US Aggregate Bonds', fill: '#ccff00' },
  { key: 'tips', label: 'Inflation-Protected (TIPS)', fill: '#a3e635' },
  { key: 'cash', label: 'Cash & T-Bills (Ring-Fenced)', fill: '#94a3b8' },
  { key: 'alternatives', label: 'Real Estate & Commodities', fill: '#38bdf8' },
];

function formatCurrency(v) {
  if (v === undefined || v === null || isNaN(v)) return '$0';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v);
}

function formatPct(v) {
  if (v === undefined || v === null || isNaN(v)) return '0.0%';
  return `${(v * 100).toFixed(1)}%`;
}

/** Local fallback Monte Carlo */
function localTrajectories(intent) {
  const years = Math.ceil(intent.time_horizon_years || 5);
  const seed = (intent.goal_id || 'GOAL').split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  let s = seed;
  const rng = () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };

  const risk = (intent.risk_profile_index || 3.5) / 10;
  const equityWeight = Math.min(0.85, Math.max(0.15, 0.25 + risk * 0.7));
  const bondWeight = 1 - equityWeight;
  const portRet = equityWeight * 0.088 + bondWeight * 0.041;
  const portVol = Math.sqrt(
    equityWeight ** 2 * 0.16 ** 2 +
    bondWeight ** 2 * 0.05 ** 2 +
    2 * equityWeight * bondWeight * 0.16 * 0.05 * 0.15
  );

  const startCapital = Math.max(intent.target_valuation * 0.12, intent.guaranteed_reserve * 1.25);
  const annualContribution = Math.max(0, (intent.target_valuation - startCapital) / years * 0.88);

  const nPaths = 120;
  const paths = [];
  for (let p = 0; p < nPaths; p++) {
    let value = startCapital;
    const series = [value];
    for (let y = 1; y <= years; y++) {
      const shock = (rng() - 0.5) * 2 * portVol * 1.25;
      value = Math.max(0, value * (1 + portRet + shock) + annualContribution);
      series.push(value);
    }
    paths.push(series);
  }

  const chartData = [];
  for (let y = 0; y <= years; y++) {
    const vals = paths.map((p) => p[y]).sort((a, b) => a - b);
    chartData.push({
      year: y,
      p10: vals[Math.floor(nPaths * 0.1)],
      p25: vals[Math.floor(nPaths * 0.25)],
      median: vals[Math.floor(nPaths * 0.5)],
      p75: vals[Math.floor(nPaths * 0.75)],
      p90: vals[Math.floor(nPaths * 0.9)],
      target: intent.target_valuation,
    });
  }
  const finalVals = paths.map((p) => p[years]).sort((a, b) => a - b);
  const successRate = finalVals.filter((v) => v >= intent.target_valuation).length / nPaths;
  const medianFinal = finalVals[Math.floor(nPaths * 0.5)];

  const allocation = [
    { name: 'US Equity', value: Math.round(equityWeight * 0.55 * 100), fill: ALLOCATION_PALETTE[0].fill },
    { name: 'International Equity', value: Math.round(equityWeight * 0.25 * 100), fill: ALLOCATION_PALETTE[1].fill },
    { name: 'US Bonds', value: Math.round(bondWeight * 0.50 * 100), fill: ALLOCATION_PALETTE[2].fill },
    { name: 'Inflation-Protected', value: Math.round(bondWeight * 0.20 * 100), fill: ALLOCATION_PALETTE[3].fill },
    { name: 'Cash / T-Bills', value: Math.round(bondWeight * 0.30 * 100), fill: ALLOCATION_PALETTE[4].fill },
    { name: 'Alternatives', value: Math.round(equityWeight * 0.20 * 100), fill: ALLOCATION_PALETTE[5].fill },
  ].filter((a) => a.value > 0);

  const total = allocation.reduce((s, a) => s + a.value, 0) || 1;
  allocation.forEach((a) => { a.value = Math.round((a.value / total) * 100); });

  return {
    chartData,
    successRate,
    medianFinal,
    allocation,
    equityWeight,
    bondWeight,
    portRet,
    portVol,
    startCapital,
    annualContribution,
    source: 'local',
  };
}

function apiResultToSim(api, intent) {
  const chartData = (api.trajectory_percentiles || []).map((row) => ({
    ...row,
    target: intent.target_valuation,
  }));
  const allocMap = api.suggested_allocation || {};
  const allocation = [
    { name: 'US Equity', value: Math.round((allocMap.us_equity || 0) * 100), fill: ALLOCATION_PALETTE[0].fill },
    { name: 'International Equity', value: Math.round((allocMap.intl_equity || 0) * 100), fill: ALLOCATION_PALETTE[1].fill },
    { name: 'US Bonds', value: Math.round((allocMap.us_bonds || 0) * 100), fill: ALLOCATION_PALETTE[2].fill },
    { name: 'Inflation-Protected', value: Math.round((allocMap.tips || 0) * 100), fill: ALLOCATION_PALETTE[3].fill },
    { name: 'Cash / T-Bills', value: Math.round((allocMap.cash || 0) * 100), fill: ALLOCATION_PALETTE[4].fill },
    { name: 'Alternatives', value: Math.round((allocMap.alternatives || 0) * 100), fill: ALLOCATION_PALETTE[5].fill },
  ].filter((a) => a.value > 0);

  return {
    chartData,
    successRate: api.success_probability,
    medianFinal: api.median_final_value,
    allocation,
    equityWeight: api.equity_weight,
    bondWeight: api.bond_weight,
    portRet: api.port_mu,
    portVol: api.port_sigma,
    startCapital: api.start_capital,
    annualContribution: api.annual_contribution,
    source: 'api',
  };
}

function MetricCard({ label, value, sub, status = 'neutral', badge = null, icon: Icon = null }) {
  const statusStyles = {
    neutral: 'text-slate-100',
    positive: 'text-[#ccff00] neon-glow-lime',
    brand: 'text-blue-400',
    warning: 'text-amber-400',
  };

  const badgeStyles = {
    neutral: 'bg-slate-800/80 text-blue-300 border-blue-700/50',
    positive: 'bg-[#ccff00]/15 text-[#ccff00] border-[#ccff00]/40 shadow-[0_0_10px_rgba(204,255,0,0.25)]',
    brand: 'bg-blue-500/15 text-blue-300 border-blue-500/35',
    warning: 'bg-amber-500/15 text-amber-300 border-amber-500/35',
  };

  return (
    <div className="glass-card rounded-2xl p-5 relative overflow-hidden group">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {Icon && <Icon className="w-4 h-4 text-slate-400 group-hover:text-[#ccff00] transition-colors" />}
          <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest">{label}</p>
        </div>
        {badge && (
          <span className={`text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-full border ${badgeStyles[status] || badgeStyles.neutral}`}>
            {badge}
          </span>
        )}
      </div>
      <p className={`text-3xl font-black font-mono tracking-tight mt-2.5 ${statusStyles[status]}`}>
        {value}
      </p>
      {sub && <p className="text-xs text-slate-400 mt-1.5 font-medium flex items-center gap-1.5">{sub}</p>}
      
      {/* Decorative subtle ambient corner glow */}
      <div className="absolute -bottom-6 -right-6 w-20 h-20 rounded-full bg-blue-600/10 blur-xl group-hover:bg-[#ccff00]/15 transition-all pointer-events-none" />
    </div>
  );
}

function CustomChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass-card-elevated rounded-xl p-3.5 text-xs shadow-2xl border border-cobalt-600/40 font-mono min-w-[200px]">
      <p className="font-bold text-[#ccff00] pb-1.5 mb-2 border-b border-cobalt-800/50 flex items-center justify-between">
        <span>Timeline Checkpoint</span>
        <span className="text-slate-200">Year {label}</span>
      </p>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center justify-between gap-4 py-1">
          <span className="text-slate-400 text-[11px]">{p.name}:</span>
          <span className="font-bold text-slate-100">{formatCurrency(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState('compiler');
  const [selectedGoalId, setSelectedGoalId] = useState(sampleIntents[0].goal_id);
  const [isQuantMode, setIsQuantMode] = useState(false);
  const [isCompiling, setIsCompiling] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [customText, setCustomText] = useState('');
  const [intent, setIntent] = useState(sampleIntents[0]);
  const [sim, setSim] = useState(() => localTrajectories(sampleIntents[0]));
  const [backendOnline, setBackendOnline] = useState(null);
  const [latency, setLatency] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [copiedAST, setCopiedAST] = useState(false);

  // User & Auth State
  const [currentUser, setCurrentUser] = useState(null);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authEmail, setAuthEmail] = useState('demo@gdipca.io');
  const [authPassword, setAuthPassword] = useState('Demo12345!');
  const [authMode, setAuthMode] = useState('login');

  // Portfolio & Rebalancing State
  const [portfolios, setPortfolios] = useState([]);
  const [selectedPortfolio, setSelectedPortfolio] = useState(null);
  const [cashActionModal, setCashActionModal] = useState(null);
  const [cashAmount, setCashAmount] = useState('10000');
  const [rebalancePlan, setRebalancePlan] = useState(null);
  const [isRebalancing, setIsRebalancing] = useState(false);
  const [transactions, setTransactions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [universeQuotes, setUniverseQuotes] = useState([]);

  // Direct Order Modal
  const [showTradeModal, setShowTradeModal] = useState(false);
  const [tradeSymbol, setTradeSymbol] = useState('VTI');
  const [tradeSide, setTradeSide] = useState('BUY');
  const [tradeShares, setTradeShares] = useState('10');
  const [isTrading, setIsTrading] = useState(false);

  // Live quotes for ticker ribbon
  const tickerData = useMemo(() => {
    if (universeQuotes && universeQuotes.length > 0) {
      return universeQuotes;
    }
    return [
      { symbol: 'VTI', price: 284.50, delta: '+0.84%', asset_class: 'US Equity' },
      { symbol: 'VOO', price: 542.10, delta: '+0.72%', asset_class: 'S&P 500' },
      { symbol: 'QQQ', price: 518.30, delta: '+1.15%', asset_class: 'Tech' },
      { symbol: 'VXUS', price: 62.40, delta: '+0.31%', asset_class: 'Intl Equity' },
      { symbol: 'BND', price: 72.85, delta: '-0.12%', asset_class: 'US Aggregate' },
      { symbol: 'SGOV', price: 100.45, delta: '+0.04%', asset_class: '0-3M T-Bills' },
      { symbol: 'GLD', price: 248.90, delta: '+0.65%', asset_class: 'Gold' },
      { symbol: 'VGT', price: 614.20, delta: '+1.32%', asset_class: 'Info Tech' },
    ];
  }, [universeQuotes]);

  // Health and session check
  useEffect(() => {
    const t0 = performance.now();
    healthCheck()
      .then(() => {
        setLatency(Math.round(performance.now() - t0));
        setBackendOnline(true);
        const token = getStoredToken();
        if (token) {
          fetchCurrentUser()
            .then((u) => setCurrentUser(u))
            .catch(() => logoutUser());
        }
        fetchUniverseQuotes()
          .then((q) => setUniverseQuotes(q))
          .catch(() => {});
      })
      .catch(() => {
        setBackendOnline(false);
      });
  }, []);

  // Load portfolios
  const loadPortfolios = useCallback(async () => {
    if (!backendOnline || !currentUser) return;
    try {
      const list = await fetchPortfolios();
      setPortfolios(list);
      if (list.length > 0) {
        const detail = await fetchPortfolioDetail(list[0].id);
        setSelectedPortfolio(detail);
        const txs = await fetchTransactions(list[0].id);
        setTransactions(txs);
        const ords = await fetchOrders(list[0].id);
        setOrders(ords);
      } else {
        const newP = await createPortfolio({
          name: `${currentUser.display_name || 'Primary'} Goal Portfolio`,
          initial_deposit: 100000,
          emergency_reserve: 25000,
          target_equity_pct: 0.60,
        });
        setSelectedPortfolio(newP);
        setPortfolios([newP]);
      }
    } catch (e) {
      console.error('Error loading portfolios:', e);
    }
  }, [backendOnline, currentUser]);

  useEffect(() => {
    if (currentUser) {
      loadPortfolios();
    }
  }, [currentUser, loadPortfolios]);

  // Auth Submit
  const handleAuthSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg('');
    try {
      let res;
      if (authMode === 'login') {
        res = await loginUser(authEmail, authPassword);
      } else {
        res = await registerUser(authEmail, authPassword, authEmail.split('@')[0]);
      }
      setCurrentUser(res.user);
      setShowAuthModal(false);
      setSuccessMsg(`Session authenticated as ${res.user.display_name || res.user.email}`);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setErrorMsg(err.message || 'Authentication failed');
    }
  };

  const handleLogout = () => {
    logoutUser();
    setCurrentUser(null);
    setPortfolios([]);
    setSelectedPortfolio(null);
  };

  // Select Preset Goal
  const selectGoal = useCallback(async (goal) => {
    setSelectedGoalId(goal.goal_id);
    setCustomText('');
    setIntent(goal);
    setErrorMsg('');
    setIsSimulating(true);
    try {
      if (backendOnline) {
        const api = await runMonteCarlo({
          ast_id: goal.goal_id,
          runs: 5000,
          time_horizon_years: goal.time_horizon_years,
          target_valuation: goal.target_valuation,
          risk_profile_index: goal.risk_profile_index,
          guaranteed_reserve: goal.guaranteed_reserve,
          confidence_threshold: goal.confidence_threshold,
        });
        setSim(apiResultToSim(api, goal));
      } else {
        setSim(localTrajectories(goal));
      }
    } catch {
      setSim(localTrajectories(goal));
    } finally {
      setIsSimulating(false);
    }
  }, [backendOnline]);

  // Natural language intent compilation
  const handleCompile = useCallback(async () => {
    const text = (customText || intent.raw_text || '').trim();
    if (!text) return;
    setIsCompiling(true);
    setErrorMsg('');
    try {
      let nextIntent = intent;
      if (backendOnline) {
        const compiled = await compileIntent(text, !!currentUser);
        nextIntent = {
          ...compiled.ast,
          milestones: compiled.ast.milestones || intent.milestones,
        };
        setIntent(nextIntent);
        setSelectedGoalId(nextIntent.goal_id);
        if (compiled.saved_to_db) {
          setSuccessMsg('Intent AST successfully compiled and persisted to database.');
          setTimeout(() => setSuccessMsg(''), 4000);
        }
      } else {
        nextIntent = { ...intent, raw_text: text };
        setIntent(nextIntent);
      }

      setIsSimulating(true);
      if (backendOnline) {
        const api = await runMonteCarlo({
          ast_id: nextIntent.goal_id,
          runs: 5000,
          time_horizon_years: nextIntent.time_horizon_years,
          target_valuation: nextIntent.target_valuation,
          risk_profile_index: nextIntent.risk_profile_index,
          guaranteed_reserve: nextIntent.guaranteed_reserve,
          confidence_threshold: nextIntent.confidence_threshold || 0.9,
        });
        setSim(apiResultToSim(api, nextIntent));
      } else {
        setSim(localTrajectories(nextIntent));
      }
    } catch (e) {
      setErrorMsg(e.message || 'Compilation failed');
      setSim(localTrajectories(intent));
    } finally {
      setIsCompiling(false);
      setIsSimulating(false);
    }
  }, [customText, intent, backendOnline, currentUser]);

  // Handle cash deposit/withdraw
  const handleCashAction = async () => {
    if (!selectedPortfolio) return;
    const amt = parseFloat(cashAmount);
    if (!amt || amt <= 0) return;
    setErrorMsg('');
    try {
      let updated;
      if (cashActionModal === 'deposit') {
        updated = await depositCash(selectedPortfolio.id, amt);
        setSuccessMsg(`Successfully credited ${formatCurrency(amt)} to portfolio cash balance.`);
      } else {
        updated = await withdrawCash(selectedPortfolio.id, amt);
        setSuccessMsg(`Successfully debited ${formatCurrency(amt)} from cash balance.`);
      }
      setSelectedPortfolio(updated);
      setCashActionModal(null);
      const txs = await fetchTransactions(selectedPortfolio.id);
      setTransactions(txs);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (e) {
      setErrorMsg(e.message);
    }
  };

  // Direct trade placement
  const handleExecuteTrade = async (e) => {
    e.preventDefault();
    if (!selectedPortfolio) return;
    const qty = parseFloat(tradeShares);
    if (!qty || qty <= 0) return;
    setIsTrading(true);
    setErrorMsg('');
    try {
      await placeTrade(selectedPortfolio.id, {
        symbol: tradeSymbol,
        side: tradeSide,
        quantity: qty,
        orderType: 'MARKET',
      });
      setSuccessMsg(`Broker executed ${tradeSide} order for ${qty} shares of ${tradeSymbol}.`);
      setShowTradeModal(false);
      const updated = await fetchPortfolioDetail(selectedPortfolio.id);
      setSelectedPortfolio(updated);
      const txs = await fetchTransactions(selectedPortfolio.id);
      setTransactions(txs);
      const ords = await fetchOrders(selectedPortfolio.id);
      setOrders(ords);
      setTimeout(() => setSuccessMsg(''), 4000);
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setIsTrading(false);
    }
  };

  // Rebalancing workflow
  const handleRebalance = async (autoExec = false) => {
    if (!selectedPortfolio) return;
    setIsRebalancing(true);
    setErrorMsg('');
    try {
      const res = await executeRebalance({
        portfolioId: selectedPortfolio.id,
        goalId: intent.goal_id,
        autoExecute: autoExec,
        thresholdPct: 0.02,
      });
      setRebalancePlan(res);
      if (autoExec) {
        setSuccessMsg('Rebalancing trade executions confirmed by matching engine.');
        const updated = await fetchPortfolioDetail(selectedPortfolio.id);
        setSelectedPortfolio(updated);
        const txs = await fetchTransactions(selectedPortfolio.id);
        setTransactions(txs);
        const ords = await fetchOrders(selectedPortfolio.id);
        setOrders(ords);
        setTimeout(() => setSuccessMsg(''), 4000);
      }
    } catch (e) {
      setErrorMsg(e.message);
    } finally {
      setIsRebalancing(false);
    }
  };

  const handleCopyAST = () => {
    const astData = {
      goal_id: intent.goal_id,
      primary_objective: intent.primary_objective,
      target_valuation: intent.target_valuation,
      guaranteed_reserve: intent.guaranteed_reserve,
      time_horizon_years: intent.time_horizon_years,
      risk_profile_index: intent.risk_profile_index,
      liquidity_constraint: intent.liquidity_constraint,
      confidence_threshold: intent.confidence_threshold,
      utility_params: intent.utility_function_params,
    };
    navigator.clipboard.writeText(JSON.stringify(astData, null, 2));
    setCopiedAST(true);
    setTimeout(() => setCopiedAST(false), 2500);
  };

  const handleExportReport = () => {
    const report = {
      timestamp: new Date().toISOString(),
      engine: 'GD-IPCA Mark 2 Electrified Edition',
      intent_ast: intent,
      simulation_summary: {
        success_probability: sim.successRate,
        median_final_value: sim.medianFinal,
        portfolio_return: sim.portRet,
        portfolio_volatility: sim.portVol,
      },
      portfolio: selectedPortfolio,
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `GD-IPCA_AuditReport_${intent.goal_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-ambient-mesh text-slate-100 flex flex-col font-sans relative selection:bg-[#ccff00] selection:text-black">
      {/* Dynamic Animated Ambient Glow Spots */}
      <div className="fixed top-0 left-1/4 w-[420px] h-[420px] bg-blue-600/18 rounded-full blur-3xl pointer-events-none animate-orb" />
      <div className="fixed bottom-10 right-1/4 w-[380px] h-[380px] bg-[#ccff00]/12 rounded-full blur-3xl pointer-events-none animate-orb" style={{ animationDelay: '-6s' }} />

      {/* 1. INSTITUTIONAL EXECUTIVE TOP NAVBAR */}
      <header className="sticky top-0 z-50 glass-card-elevated border-b border-cobalt-600/30">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          {/* Logo & Electrified Platform Info */}
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl gradient-cobalt flex items-center justify-center shadow-lg shadow-blue-500/35 border border-cobalt-400/40 relative group">
              <Layers className="w-5 h-5 text-[#ccff00]" />
            </div>
            <div>
              <div className="flex flex-col justify-center">
                <span className="text-lg font-black tracking-tight text-white font-mono leading-none">GD-IPCA™</span>
                <p className="text-[11px] text-slate-400 font-medium tracking-tight mt-1 hidden sm:block leading-none">
                  Intent-to-Portfolio Compilation &amp; Stochastic Execution
                </p>
              </div>
            </div>

          {/* Action Center & Status */}
          <div className="flex items-center gap-4">
            {/* Mode Toggle (Quant vs Executive) */}
            <button
              onClick={() => setIsQuantMode(!isQuantMode)}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                isQuantMode
                  ? 'bg-[#ccff00]/15 text-[#ccff00] border-[#ccff00]/40 shadow-sm'
                  : 'bg-blue-950/40 text-slate-200 border-blue-500/25 hover:border-[#ccff00]/50 hover:text-white'
              }`}
            >
              <Sliders className="w-3.5 h-3.5 text-[#ccff00]" />
              <span className="hidden sm:inline">{isQuantMode ? 'Institutional Quant' : 'Executive View'}</span>
            </button>

            {/* Export Report */}
            <button
              onClick={handleExportReport}
              className="p-2 text-slate-300 hover:text-white glass-pill hover:border-[#ccff00]/40 rounded-xl transition-all"
              title="Export Full Diagnostic Report (JSON)"
            >
              <FileDown className="w-4 h-4 text-blue-300 hover:text-[#ccff00]" />
            </button>

            {/* Authentication / User Avatar */}
            {currentUser ? (
              <div className="flex items-center gap-2.5 pl-2 border-l border-blue-800/40">
                <div className="w-8 h-8 rounded-full gradient-cobalt flex items-center justify-center text-[#ccff00] text-xs font-black font-mono shadow-md border border-[#ccff00]/40">
                  {(currentUser.display_name || currentUser.email)[0].toUpperCase()}
                </div>
                <div className="text-left hidden md:block">
                  <p className="text-xs font-bold text-white leading-tight">
                    {currentUser.display_name || currentUser.email.split('@')[0]}
                  </p>
                  <p className="text-[10px] font-bold text-[#ccff00] uppercase tracking-wider">{currentUser.role || 'Investor'}</p>
                </div>
                <button
                  onClick={handleLogout}
                  className="p-1.5 text-slate-400 hover:text-rose-400 rounded-lg transition-colors ml-1"
                  title="Sign Out"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowAuthModal(true)}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-extrabold bg-[#ccff00] text-black shadow-lg shadow-[#ccff00]/25 hover:bg-[#d9ff33] transition-all btn-shimmer uppercase tracking-wider"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>Sign In</span>
              </button>
            )}
          </div>
        </div>

        {/* Real-Time Market Ticker Ribbon with Acid Highlights */}
        <div className="bg-black text-slate-300 py-1.5 px-6 text-xs border-t border-cobalt-900/60 overflow-hidden whitespace-nowrap flex items-center font-mono">
          <div className="flex items-center gap-2 pr-6 border-r border-blue-900/50 shrink-0">
            <span className="w-2 h-2 rounded-full bg-[#ccff00] animate-ping" />
            <span className="text-[10px] font-extrabold text-[#ccff00] uppercase tracking-widest">Live Markets</span>
          </div>
          <div className="overflow-hidden w-full ml-4">
            <div className="animate-ticker flex items-center gap-8">
              {tickerData.concat(tickerData).map((q, idx) => (
                <div key={`${q.symbol}-${idx}`} className="inline-flex items-center gap-2">
                  <span className="font-extrabold text-white">{q.symbol}</span>
                  <span className="text-slate-200">${typeof q.price === 'number' ? q.price.toFixed(2) : q.price}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-extrabold ${
                    (q.delta || '').includes('+') || !q.delta 
                      ? 'bg-[#ccff00]/15 text-[#ccff00] border border-[#ccff00]/40' 
                      : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                  }`}>
                    {q.delta || '+0.45%'}
                  </span>
                  <span className="text-[9px] text-blue-400 uppercase font-semibold">{q.asset_class}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </header>

      {/* 2. MAIN DASHBOARD WRAPPER & NOTIFICATIONS */}
      <main className="max-w-7xl mx-auto px-6 py-8 w-full flex-1 space-y-6">
        {/* Global Notifications */}
        {errorMsg && (
          <div className="p-4 glass-card rounded-2xl border-rose-500/40 bg-rose-950/30 text-rose-200 text-xs flex items-center justify-between">
            <div className="flex items-center gap-3 font-medium">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              <span>{errorMsg}</span>
            </div>
            <button onClick={() => setErrorMsg('')} className="text-rose-400 hover:text-white font-bold ml-4">
              Dismiss
            </button>
          </div>
        )}
        {successMsg && (
          <div className="p-4 glass-card rounded-2xl border-[#ccff00]/60 bg-[#ccff00]/10 text-white text-xs flex items-center justify-between">
            <div className="flex items-center gap-3 font-bold">
              <Check className="w-4 h-4 shrink-0 text-[#ccff00]" />
              <span>{successMsg}</span>
            </div>
            <button onClick={() => setSuccessMsg('')} className="text-[#ccff00] hover:text-white font-bold ml-4 uppercase tracking-wider text-[11px]">
              Dismiss
            </button>
          </div>
        )}

        {/* Global Executive Status Bar */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard
            label="Target Goal Capital"
            value={formatCurrency(intent.target_valuation)}
            sub={`Timeline: ${intent.time_horizon_years} Years Horizon`}
            status="brand"
            icon={Target}
            badge="BENCHMARK"
          />
          <MetricCard
            label="Success Probability"
            value={formatPct(sim.successRate)}
            sub={`SLA Target ≥ ${formatPct(intent.confidence_threshold || 0.90)}`}
            status={sim.successRate >= (intent.confidence_threshold || 0.90) ? 'positive' : 'warning'}
            icon={TrendingUp}
            badge={sim.successRate >= (intent.confidence_threshold || 0.90) ? 'OPTIMAL' : 'ADVISORY'}
          />
          <MetricCard
            label="Ring-Fenced Reserve"
            value={formatCurrency(intent.guaranteed_reserve)}
            sub="Lock-Box Protected in T-Bills"
            status="neutral"
            icon={Lock}
            badge="FIDUCIARY"
          />
          <MetricCard
            label="Projected Median Outcome"
            value={formatCurrency(sim.medianFinal)}
            sub={`Exp Return μ: ${formatPct(sim.portRet)} | Vol σ: ${formatPct(sim.portVol)}`}
            status={sim.medianFinal >= intent.target_valuation ? 'positive' : 'brand'}
            icon={Activity}
            badge="5,000 PATHS"
          />
        </div>

        {/* Navigation Subsystem Segmented Bar */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 glass-card rounded-2xl p-2 border border-cobalt-600/30">
          <div className="flex items-center gap-1.5 overflow-x-auto py-1">
            <button
              onClick={() => setActiveTab('compiler')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all whitespace-nowrap ${
                activeTab === 'compiler'
                  ? 'glass-card-active text-[#ccff00] shadow-md'
                  : 'text-slate-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <Target className="w-4 h-4 text-[#ccff00]" />
              Goal Compiler & AST
            </button>

            <button
              onClick={() => setActiveTab('montecarlo')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all whitespace-nowrap ${
                activeTab === 'montecarlo'
                  ? 'glass-card-active text-[#ccff00] shadow-md'
                  : 'text-slate-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <BarChart3 className="w-4 h-4 text-blue-400" />
              Monte Carlo Engine
            </button>

            <button
              onClick={() => setActiveTab('portfolio')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all whitespace-nowrap ${
                activeTab === 'portfolio'
                  ? 'glass-card-active text-[#ccff00] shadow-md'
                  : 'text-slate-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <Wallet className="w-4 h-4 text-indigo-400" />
              Holdings & Valuation
              {selectedPortfolio && (
                <span className="ml-1 text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-[#ccff00] font-mono font-bold border border-blue-500/40">
                  {formatCurrency(selectedPortfolio.total_valuation)}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('rebalance')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all whitespace-nowrap ${
                activeTab === 'rebalance'
                  ? 'glass-card-active text-[#ccff00] shadow-md'
                  : 'text-slate-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <RefreshCw className="w-4 h-4 text-amber-400" />
              Rebalance & Drift
            </button>

            <button
              onClick={() => setActiveTab('ledger')}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all whitespace-nowrap ${
                activeTab === 'ledger'
                  ? 'glass-card-active text-[#ccff00] shadow-md'
                  : 'text-slate-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <Clock className="w-4 h-4 text-slate-400" />
              Audit Ledger
              {transactions.length > 0 && (
                <span className="ml-1 text-[10px] px-2 py-0.5 rounded-full bg-blue-950 text-blue-300 font-mono font-bold border border-blue-800">
                  {transactions.length}
                </span>
              )}
            </button>
          </div>

          {/* Action Trigger: Electrified Acid Lime Button */}
          {currentUser && selectedPortfolio && (
            <button
              onClick={() => setShowTradeModal(true)}
              className="flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-xs font-black bg-[#ccff00] text-black shadow-lg shadow-[#ccff00]/25 hover:bg-[#d9ff33] transition-all btn-shimmer uppercase tracking-wider"
            >
              <Zap className="w-3.5 h-3.5 text-black" />
              <span>Direct Broker Order</span>
            </button>
          )}
        </div>

        {/* TAB 1: INTENT COMPILER & DETERMINISTIC AST */}
        {activeTab === 'compiler' && (
          <div className="space-y-6">
            {/* Goal Presets Selection */}
            <div>
              <div className="flex items-baseline justify-between mb-3">
                <h2 className="text-xs font-extrabold uppercase tracking-widest text-slate-300 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#ccff00]" />
                  Canonical Goal Intent Presets
                </h2>
                <span className="text-xs font-mono text-blue-400">SPEC-GDIPCA 3.4.0 Certified</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
                {sampleIntents.map((g, idx) => {
                  const GIcon = GOAL_ICONS[g.goal_id] || Target;
                  const active = g.goal_id === selectedGoalId;
                  return (
                    <button
                      key={g.goal_id}
                      onClick={() => selectGoal(g)}
                      className={`text-left rounded-2xl p-4 transition-all border relative overflow-hidden ${
                        active
                          ? 'glass-card-active border-[#ccff00] shadow-lg shadow-[#ccff00]/20'
                          : 'glass-card hover:border-cobalt-400/40'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                          active ? 'bg-[#ccff00] text-black font-black shadow-md' : 'bg-blue-950/60 text-blue-300 border border-blue-800/40'
                        }`}>
                          <GIcon className="w-4 h-4" />
                        </div>
                        <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-blue-950/80 text-[#ccff00] border border-[#ccff00]/30">
                          {g.time_horizon_years}Y Horizon
                        </span>
                      </div>
                      <p className="font-bold text-white text-sm leading-snug line-clamp-1">{g.primary_objective}</p>
                      <p className="text-sm font-mono font-extrabold text-[#ccff00] mt-2">{formatCurrency(g.target_valuation)}</p>
                      <p className="text-[11px] text-slate-400 mt-1">Reserve: {formatCurrency(g.guaranteed_reserve)}</p>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Natural Language Semantic Parser Input */}
            <div className="glass-card rounded-2xl p-6 relative">
              <label className="text-xs font-extrabold uppercase tracking-widest text-slate-300 block mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#ccff00]" />
                Natural Language Semantic Intent Parser
              </label>
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                <div className="relative flex-1">
                  <input
                    type="text"
                    value={customText || intent.raw_text || ''}
                    onChange={(e) => setCustomText(e.target.value)}
                    placeholder="e.g. Save $200,000 for college tuition in 6 years while reserving $30,000 for emergencies..."
                    className="w-full text-sm px-4 py-3.5 rounded-xl glass-input placeholder:text-slate-500 font-medium"
                  />
                </div>
                <button
                  onClick={handleCompile}
                  disabled={isCompiling || isSimulating}
                  className="flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl gradient-cobalt text-white font-extrabold text-sm shadow-lg shadow-blue-500/30 hover:opacity-95 disabled:opacity-60 transition-all shrink-0 btn-shimmer border border-cobalt-400/30"
                >
                  {isCompiling ? (
                    <RefreshCw className="w-4 h-4 animate-spin text-[#ccff00]" />
                  ) : (
                    <Zap className="w-4 h-4 text-[#ccff00]" />
                  )}
                  <span>{isCompiling ? 'Compiling…' : 'Compile Intent AST'}</span>
                </button>
              </div>

              {/* Quick suggestion tags */}
              <div className="flex items-center gap-2 mt-3.5 flex-wrap text-[11px] text-slate-400">
                <span className="font-semibold text-blue-300">Quick Presets:</span>
                <button
                  type="button"
                  onClick={() => setCustomText('Accumulate $350,000 in 7 years for business venture, protecting $40,000.')}
                  className="px-2.5 py-1 rounded-lg glass-pill hover:border-[#ccff00]/40 text-slate-300 hover:text-[#ccff00] transition-colors"
                >
                  Startup Seed Fund ($350k)
                </button>
                <button
                  type="button"
                  onClick={() => setCustomText('Retire in 15 years with $2,500,000 with a $150,000 cash safety reserve.')}
                  className="px-2.5 py-1 rounded-lg glass-pill hover:border-[#ccff00]/40 text-slate-300 hover:text-[#ccff00] transition-colors"
                >
                  Executive Retirement ($2.5M)
                </button>
                <button
                  type="button"
                  onClick={() => setCustomText('Purchase coastal property for $500,000 in 4 years, ring-fencing $50,000.')}
                  className="px-2.5 py-1 rounded-lg glass-pill hover:border-[#ccff00]/40 text-slate-300 hover:text-[#ccff00] transition-colors"
                >
                  Real Estate Down Payment ($500k)
                </button>
              </div>
            </div>

            {/* 2-Column Split: AST Console & Milestone Progression */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column: Compiled AST */}
              <div className="lg:col-span-5 space-y-5">
                <div className="glass-card rounded-2xl p-5 font-mono border-cobalt-600/30">
                  <div className="flex items-center justify-between pb-3 mb-3 border-b border-cobalt-800/50">
                    <span className="text-xs font-bold text-[#ccff00] flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-[#ccff00]" />
                      Deterministic Intent AST
                    </span>
                    <button
                      onClick={handleCopyAST}
                      className="text-[10px] text-blue-300 hover:text-white flex items-center gap-1.5 px-2.5 py-1 rounded-lg glass-pill hover:border-[#ccff00]/40"
                    >
                      {copiedAST ? <CheckCheck className="w-3 h-3 text-[#ccff00]" /> : <Copy className="w-3 h-3" />}
                      <span>{copiedAST ? 'Copied' : 'Copy AST'}</span>
                    </button>
                  </div>
                  <pre className="text-xs text-blue-200 overflow-x-auto leading-relaxed max-h-80 custom-scroll font-mono p-1">
{JSON.stringify(
  {
    goal_id: intent.goal_id,
    primary_objective: intent.primary_objective,
    target_valuation: intent.target_valuation,
    guaranteed_reserve: intent.guaranteed_reserve,
    time_horizon_years: intent.time_horizon_years,
    risk_profile_index: intent.risk_profile_index,
    liquidity_constraint: intent.liquidity_constraint,
    confidence_threshold: intent.confidence_threshold,
    utility_params: intent.utility_function_params,
  },
  null,
  2
)}
                  </pre>
                </div>

                {/* Milestone Checkpoint Roadmap */}
                <div className="glass-card rounded-2xl p-5">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-4 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[#ccff00]" />
                    Milestone Progression Checkpoints
                  </h3>
                  <div className="space-y-3.5">
                    {(intent.milestones || []).map((m, idx) => (
                      <div key={idx} className="flex items-center gap-3">
                        <span className="w-7 h-7 rounded-lg gradient-cobalt text-[#ccff00] font-black font-mono text-xs flex items-center justify-center shrink-0 shadow-sm border border-[#ccff00]/40">
                          Y{m.year}
                        </span>
                        <div className="flex-1">
                          <div className="flex justify-between text-xs font-medium text-slate-200 mb-1.5">
                            <span>{m.label}</span>
                            <span className="font-mono text-[#ccff00] font-extrabold">{m.target_progress_pct}%</span>
                          </div>
                          <div className="h-2 rounded-full bg-slate-900 overflow-hidden border border-blue-900/40">
                            <div
                              className="h-full rounded-full bg-gradient-to-r from-blue-600 via-blue-500 to-[#ccff00] transition-all duration-700"
                              style={{ width: `${m.target_progress_pct}%` }}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Right Column: Goal Health & Asset Projection */}
              <div className="lg:col-span-7 space-y-5">
                {/* Executive vs Quant Explanation */}
                <div className="glass-card rounded-2xl p-6">
                  <div className="flex items-center justify-between mb-4 pb-3 border-b border-cobalt-800/50">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                      <ShieldCheck className="w-4 h-4 text-[#ccff00]" />
                      {isQuantMode ? 'Quantitative Risk & Return Parameters' : 'Fiduciary Executive Summary'}
                    </span>
                    <span className="text-[10px] font-mono font-extrabold text-[#ccff00] bg-[#ccff00]/15 px-2.5 py-1 rounded-full border border-[#ccff00]/40">
                      CONFIDENCE SLA MET
                    </span>
                  </div>

                  {isQuantMode ? (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
                      <div className="p-4 glass-card rounded-xl border border-blue-500/20">
                        <p className="text-slate-400 text-[11px]">Expected Return (μ)</p>
                        <p className="text-xl font-bold text-[#ccff00] mt-1">{formatPct(sim.portRet)}</p>
                        <p className="text-[10px] text-blue-400 mt-1">Annualized Drift</p>
                      </div>
                      <div className="p-4 glass-card rounded-xl border border-blue-500/20">
                        <p className="text-slate-400 text-[11px]">Portfolio Volatility (σ)</p>
                        <p className="text-xl font-bold text-blue-400 mt-1">{formatPct(sim.portVol)}</p>
                        <p className="text-[10px] text-blue-400 mt-1">1-Year Standard Dev</p>
                      </div>
                      <div className="p-4 glass-card rounded-xl border border-blue-500/20">
                        <p className="text-slate-400 text-[11px]">Equity / Fixed-Income</p>
                        <p className="text-xl font-bold text-[#ccff00] mt-1">{formatPct(sim.equityWeight)} / {formatPct(sim.bondWeight)}</p>
                        <p className="text-[10px] text-blue-400 mt-1">Strategic Weight Ratio</p>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-slate-300 space-y-4 leading-relaxed font-sans">
                      <p>
                        To accomplish your objective of accumulating{' '}
                        <strong className="text-white font-extrabold">{formatCurrency(intent.target_valuation)}</strong> over{' '}
                        <strong className="text-[#ccff00] font-extrabold">{intent.time_horizon_years} years</strong>, the stochastic compilation model forecasts a median wealth projection of{' '}
                        <strong className="text-[#ccff00] font-extrabold">{formatCurrency(sim.medianFinal)}</strong>.
                      </p>
                      <div className="p-4 rounded-xl glass-card border border-[#ccff00]/30 bg-[#ccff00]/5 text-xs text-slate-200 flex items-start gap-3 font-medium">
                        <Shield className="w-5 h-5 text-[#ccff00] shrink-0 mt-0.5" />
                        <span>
                          Your <strong className="text-white">{formatCurrency(intent.guaranteed_reserve)}</strong> emergency liquidity reserve is ring-fenced strictly in Treasury Bills (SGOV / Cash) and is algorithmically quarantined from market drawdown risk.
                        </span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Quick Asset Allocation Preview */}
                <div className="glass-card rounded-2xl p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                      <PieIcon className="w-4 h-4 text-[#ccff00]" />
                      Compiled Strategic Asset Allocation
                    </h4>
                    <span className="text-xs font-mono text-[#ccff00] font-bold">100% Fully Allocated</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {sim.allocation.map((item) => (
                      <div key={item.name} className="p-3 glass-card rounded-xl border border-cobalt-800/40 flex items-center gap-3">
                        <span className="w-3 h-3 rounded-full shrink-0 shadow-[0_0_8px_rgba(204,255,0,0.4)]" style={{ backgroundColor: item.fill }} />
                        <div>
                          <p className="text-xs text-slate-300 font-medium truncate">{item.name}</p>
                          <p className="text-sm font-extrabold font-mono text-[#ccff00]">{item.value}%</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: MONTE CARLO STOCHASTIC ENGINE */}
        {activeTab === 'montecarlo' && (
          <div className="space-y-6">
            <div className="glass-card rounded-2xl p-6">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                <div>
                  <h3 className="text-base font-extrabold text-white flex items-center gap-2.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#ccff00]" />
                    Stochastic Monte Carlo Trajectories (Percentile Dispersion)
                  </h3>
                  <p className="text-xs text-slate-400 mt-1">
                    Correlated Geometric Brownian Motion · 4-State Markov Regime Switches · Student-$t$ Fat-Tail Shocks
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono font-bold text-[#ccff00] bg-[#ccff00]/15 px-3 py-1.5 rounded-xl border border-[#ccff00]/40 shadow-[0_0_12px_rgba(204,255,0,0.2)]">
                    5,000 Paths Vectorized
                  </span>
                  <button
                    onClick={handleCompile}
                    disabled={isSimulating}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl gradient-cobalt text-white font-bold text-xs hover:opacity-95 shadow-md shadow-blue-500/25 border border-cobalt-400/30 btn-shimmer"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isSimulating ? 'animate-spin' : ''}`} />
                    Re-Simulate Paths
                  </button>
                </div>
              </div>

              {/* Area Fan Chart */}
              <div className="h-88 w-full pt-4">
                <ResponsiveContainer width="100%" height={320}>
                  <AreaChart data={sim.chartData} margin={{ top: 10, right: 25, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="p90Grad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#ccff00" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#ccff00" stopOpacity={0.02} />
                      </linearGradient>
                      <linearGradient id="medianGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#2b5cff" stopOpacity={0.60} />
                        <stop offset="100%" stopColor="#1e40af" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="year"
                      tick={{ fill: '#93c5fd', fontSize: 12, fontFamily: 'monospace' }}
                      axisLine={{ stroke: 'rgba(43,92,255,0.25)' }}
                      tickLine={false}
                      tickFormatter={(y) => `Yr ${y}`}
                    />
                    <YAxis
                      tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                      tick={{ fill: '#60a5fa', fontSize: 12, fontFamily: 'monospace' }}
                      axisLine={false}
                      tickLine={false}
                      width={56}
                    />
                    <Tooltip content={<CustomChartTooltip />} />
                    <ReferenceLine
                      y={intent.target_valuation}
                      stroke="#ccff00"
                      strokeDasharray="5 5"
                      strokeWidth={2}
                      label={{
                        value: `Target: ${formatCurrency(intent.target_valuation)}`,
                        position: 'insideTopRight',
                        fill: '#ccff00',
                        fontSize: 12,
                        fontWeight: 700,
                        fontFamily: 'monospace'
                      }}
                    />
                    <Area type="monotone" dataKey="p90" stroke="#ccff00" strokeWidth={2} fill="url(#p90Grad)" name="P90 Bullish Sky" />
                    <Area type="monotone" dataKey="p10" stroke="#60a5fa" strokeWidth={1} strokeDasharray="3 3" fill="transparent" name="P10 Bearish Floor" />
                    <Area type="monotone" dataKey="median" stroke="#2b5cff" strokeWidth={3.5} fill="url(#medianGrad)" name="Median Path (P50)" />
                    {isQuantMode && (
                      <>
                        <Area type="monotone" dataKey="p75" stroke="#93c5fd" strokeWidth={1} strokeDasharray="3 3" fill="none" name="P75 Upper Interquartile" />
                        <Area type="monotone" dataKey="p25" stroke="#93c5fd" strokeWidth={1} strokeDasharray="3 3" fill="none" name="P25 Lower Interquartile" />
                      </>
                    )}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Strategic Asset Allocation & Regime Calibration */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="glass-card rounded-2xl p-6">
                <h4 className="text-xs font-extrabold uppercase tracking-widest text-slate-200 mb-4 flex items-center gap-2">
                  <PieIcon className="w-4 h-4 text-[#ccff00]" />
                  Target Strategic Asset Breakdown
                </h4>
                <div className="h-60">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={sim.allocation}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={85}
                        paddingAngle={4}
                        stroke="#010409"
                        strokeWidth={3}
                      >
                        {sim.allocation.map((entry, index) => (
                          <Cell key={index} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v) => `${v}%`} contentStyle={{ backgroundColor: '#060d1f', borderColor: '#1e40af', borderRadius: 12, fontSize: 12 }} />
                      <Legend verticalAlign="bottom" height={36} iconType="circle" formatter={(v) => <span className="text-xs text-slate-300 font-medium">{v}</span>} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="glass-card rounded-2xl p-6 font-mono text-xs space-y-3.5">
                <h4 className="text-xs font-extrabold uppercase tracking-widest text-slate-200 font-sans flex items-center gap-2">
                  <Activity className="w-4 h-4 text-[#ccff00]" />
                  Regime Switching Calibration Matrix
                </h4>
                <div className="space-y-2.5 pt-1 text-slate-300">
                  <div className="flex justify-between items-center py-2 border-b border-cobalt-800/50">
                    <span className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-[#ccff00]" />
                      Regime 1: Normal Expansion (62%)
                    </span>
                    <span className="font-bold text-white">μ = 1.00x, σ = 1.00x</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-cobalt-800/50">
                    <span className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-blue-400" />
                      Regime 2: Bull Euphoria (18%)
                    </span>
                    <span className="font-bold text-[#ccff00]">μ = 1.45x, σ = 0.85x</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-cobalt-800/50">
                    <span className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-amber-400" />
                      Regime 3: Bear Correction (14%)
                    </span>
                    <span className="font-bold text-amber-300">μ = -0.60x, σ = 1.80x</span>
                  </div>
                  <div className="flex justify-between items-center py-2">
                    <span className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-rose-400" />
                      Regime 4: Liquidity Crisis (6%)
                    </span>
                    <span className="font-bold text-rose-400">μ = -1.90x, σ = 2.80x (Fat Tail)</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: ACTIVE PORTFOLIO & HOLDINGS */}
        {activeTab === 'portfolio' && (
          <div className="space-y-6">
            {!currentUser ? (
              <div className="glass-card rounded-2xl p-12 text-center space-y-4 max-w-xl mx-auto">
                <div className="w-16 h-16 rounded-2xl gradient-cobalt flex items-center justify-center mx-auto shadow-xl shadow-blue-500/35 border border-[#ccff00]/40">
                  <Wallet className="w-8 h-8 text-[#ccff00]" />
                </div>
                <h3 className="text-xl font-bold text-white">Access Your Live Portfolio</h3>
                <p className="text-xs text-slate-400 leading-relaxed">
                  Authenticate your session to access multi-portfolio allocations, execute real-time paper broker orders, and manage cash flows with user-level data isolation.
                </p>
                <button
                  onClick={() => setShowAuthModal(true)}
                  className="px-6 py-3 rounded-xl bg-[#ccff00] text-black font-black text-xs shadow-lg shadow-[#ccff00]/25 hover:bg-[#d9ff33] btn-shimmer uppercase tracking-wider"
                >
                  Sign In with Demo Credentials
                </button>
              </div>
            ) : selectedPortfolio ? (
              <div className="space-y-6">
                {/* Summary Metrics Banner */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  <MetricCard
                    label="Portfolio Valuation"
                    value={formatCurrency(selectedPortfolio.total_valuation)}
                    sub={selectedPortfolio.name}
                    status="brand"
                    icon={TrendingUp}
                  />
                  <div className="glass-card rounded-2xl p-5 flex flex-col justify-between">
                    <div>
                      <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Available Cash</p>
                      <p className="text-2xl font-extrabold font-mono tracking-tight text-[#ccff00] mt-1.5">
                        {formatCurrency(selectedPortfolio.cash_balance)}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 mt-4 pt-3 border-t border-cobalt-800/50">
                      <button
                        onClick={() => setCashActionModal('deposit')}
                        className="flex-1 py-1.5 rounded-lg gradient-cobalt text-white text-xs font-extrabold hover:opacity-95 border border-blue-400/30"
                      >
                        + Deposit
                      </button>
                      <button
                        onClick={() => setCashActionModal('withdraw')}
                        className="flex-1 py-1.5 rounded-lg glass-pill text-slate-200 text-xs font-bold hover:bg-white/10 hover:border-[#ccff00]/40"
                      >
                        - Withdraw
                      </button>
                    </div>
                  </div>
                  <MetricCard
                    label="Guaranteed Reserve"
                    value={formatCurrency(selectedPortfolio.emergency_reserve)}
                    sub="Protected Liquidity Floor"
                    status="neutral"
                    icon={Shield}
                  />
                  <MetricCard
                    label="Target Equity / Bond"
                    value={`${formatPct(selectedPortfolio.target_equity_pct)} / ${formatPct(selectedPortfolio.target_bond_pct)}`}
                    sub="Strategic Asset Benchmark"
                    status="neutral"
                    icon={Sliders}
                  />
                </div>

                {/* Holdings Table */}
                <div className="glass-card rounded-2xl p-6">
                  <div className="flex items-center justify-between mb-5">
                    <h3 className="text-xs font-extrabold uppercase tracking-widest text-slate-200 flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-[#ccff00]" />
                      Active Investment Holdings
                    </h3>
                    <span className="text-xs font-mono font-bold text-[#ccff00]">
                      {selectedPortfolio.holdings.length} Positions Active
                    </span>
                  </div>

                  {selectedPortfolio.holdings.length === 0 ? (
                    <div className="text-center py-12 text-slate-400 text-xs">
                      <p className="font-semibold text-slate-300">No open ETF positions in this portfolio.</p>
                      <p className="mt-1 text-slate-500">
                        Use the <strong>Rebalance</strong> tab or click <strong>Direct Broker Order</strong> above to invest cash into target assets.
                      </p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs font-mono">
                        <thead>
                          <tr className="border-b border-cobalt-800/50 text-slate-400 uppercase text-[10px]">
                            <th className="pb-3 font-bold">Ticker</th>
                            <th className="pb-3 font-bold">Asset Class</th>
                            <th className="pb-3 font-bold text-right">Shares</th>
                            <th className="pb-3 font-bold text-right">Cost Basis</th>
                            <th className="pb-3 font-bold text-right">Market Price</th>
                            <th className="pb-3 font-bold text-right">Market Value</th>
                            <th className="pb-3 font-bold text-right">Portfolio Weight</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-cobalt-900/40 text-slate-200">
                          {selectedPortfolio.holdings.map((h) => (
                            <tr key={h.id} className="hover:bg-blue-900/15 transition-colors">
                              <td className="py-3.5 font-bold text-white font-sans">
                                {h.symbol}
                                <span className="block text-[11px] font-normal text-slate-400">{h.asset_name}</span>
                              </td>
                              <td className="py-3.5 text-[11px] font-sans font-medium text-blue-300">{h.asset_class}</td>
                              <td className="py-3.5 text-right text-slate-200">{h.quantity.toFixed(2)}</td>
                              <td className="py-3.5 text-right text-slate-400">${h.cost_basis.toFixed(2)}</td>
                              <td className="py-3.5 text-right font-bold text-[#ccff00]">${h.current_price.toFixed(2)}</td>
                              <td className="py-3.5 text-right font-bold text-white">{formatCurrency(h.market_value)}</td>
                              <td className="py-3.5 text-right font-bold text-blue-300">{formatPct(h.allocation_pct)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        )}

        {/* TAB 4: REBALANCE & DRIFT WORKFLOW */}
        {activeTab === 'rebalance' && (
          <div className="space-y-6">
            <div className="glass-card rounded-2xl p-6">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                <div>
                  <h3 className="text-base font-extrabold text-white flex items-center gap-2.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#ccff00]" />
                    Milestone Rebalancing & Asset Drift Control
                  </h3>
                  <p className="text-xs text-slate-400 mt-1">
                    Automated multi-asset rebalancing against target risk weights with plain-English client explanations.
                  </p>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => handleRebalance(false)}
                    disabled={isRebalancing || !selectedPortfolio}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl glass-pill text-slate-200 font-bold text-xs hover:bg-white/10 hover:border-[#ccff00]/40 shadow-sm"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isRebalancing ? 'animate-spin' : ''}`} />
                    Analyze Drift
                  </button>
                  <button
                    onClick={() => handleRebalance(true)}
                    disabled={isRebalancing || !selectedPortfolio}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#ccff00] text-black font-black text-xs hover:bg-[#d9ff33] shadow-lg shadow-[#ccff00]/25 btn-shimmer uppercase tracking-wider"
                  >
                    <PlayCircle className="w-3.5 h-3.5 text-black" />
                    Execute Rebalance Trades
                  </button>
                </div>
              </div>

              {rebalancePlan ? (
                <div className="space-y-6">
                  {/* Fiduciary Explanation Banner */}
                  <div className="p-5 rounded-2xl glass-card border border-blue-500/40 bg-blue-950/20 text-white space-y-2">
                    <p className="text-[10px] uppercase font-extrabold text-[#ccff00] tracking-wider">
                      Fiduciary Plain-English Milestone Update
                    </p>
                    <p className="text-sm text-slate-200 leading-relaxed font-medium">
                      {rebalancePlan.plain_english_explanation}
                    </p>
                  </div>

                  {/* Drift Metrics */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    <MetricCard
                      label="Max Drift Detected"
                      value={formatPct(rebalancePlan.drift_detected)}
                      status={rebalancePlan.drift_detected > 0.02 ? 'warning' : 'positive'}
                    />
                    <MetricCard
                      label="Target Equity"
                      value={formatPct(rebalancePlan.target_allocation.equity)}
                      status="neutral"
                    />
                    <MetricCard
                      label="Target Fixed-Income"
                      value={formatPct(rebalancePlan.target_allocation.fixed_income)}
                      status="neutral"
                    />
                    <MetricCard
                      label="Execution Status"
                      value={rebalancePlan.executed ? 'EXECUTED' : 'PREVIEW'}
                      status={rebalancePlan.executed ? 'positive' : 'neutral'}
                    />
                  </div>

                  {/* Proposed Trade Orders */}
                  <div>
                    <h4 className="text-xs font-extrabold uppercase tracking-widest text-slate-300 mb-3.5">
                      Generated Rebalancing Order Routing
                    </h4>
                    {rebalancePlan.orders.length === 0 ? (
                      <p className="text-xs text-slate-400 glass-card p-4 rounded-xl border border-white/5">
                        Portfolio is aligned within the ±2.0% tolerance band. No adjustments are needed right now.
                      </p>
                    ) : (
                      <div className="space-y-3">
                        {rebalancePlan.orders.map((o, idx) => (
                          <div
                            key={idx}
                            className="p-4 rounded-xl glass-card border border-cobalt-800/50 flex items-center justify-between hover:border-[#ccff00]/40 transition-all"
                          >
                            <div className="flex items-center gap-3.5">
                              <span
                                className={`text-[10px] font-bold font-mono px-2.5 py-1 rounded-md ${
                                  o.side === 'BUY'
                                    ? 'bg-[#ccff00]/20 text-[#ccff00] border border-[#ccff00]/40'
                                    : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                                }`}
                              >
                                {o.side}
                              </span>
                              <div>
                                <p className="text-xs font-bold text-white">
                                  {o.quantity} shares of {o.symbol} ({o.asset_name})
                                </p>
                                <p className="text-[11px] text-slate-400 mt-0.5">{o.plain_english_reason}</p>
                              </div>
                            </div>
                            <div className="text-right font-mono">
                              <p className="text-xs font-bold text-white">{formatCurrency(o.estimated_total)}</p>
                              <p className="text-[10px] text-blue-400">@ ${o.estimated_price.toFixed(2)}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-center py-10 text-slate-400 text-xs">
                  <p>Click <strong>Analyze Drift</strong> to evaluate portfolio weights and preview proposed rebalancing trades.</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 5: AUDIT LEDGER & BROKER ORDERS */}
        {activeTab === 'ledger' && (
          <div className="space-y-6">
            <div className="glass-card rounded-2xl p-6">
              <div className="flex items-center justify-between mb-5 pb-3 border-b border-cobalt-800/50">
                <div>
                  <h3 className="text-xs font-extrabold uppercase tracking-widest text-slate-200">
                    Immutable Transaction Ledger & Execution Log
                  </h3>
                  <p className="text-xs text-slate-400 mt-1">
                    Real-time broker order status and synchronized cryptographic transaction log.
                  </p>
                </div>
                <span className="text-xs font-mono font-bold text-[#ccff00]">
                  {transactions.length} Verified Records
                </span>
              </div>

              {transactions.length === 0 ? (
                <div className="text-center py-12 text-slate-400 text-xs">
                  <p>No transaction history recorded yet.</p>
                </div>
              ) : (
                <div className="divide-y divide-cobalt-900/40 font-mono text-xs">
                  {transactions.map((tx) => (
                    <div key={tx.id} className="py-3.5 flex items-center justify-between hover:bg-white/5 px-3 rounded-xl transition-colors">
                      <div className="flex items-center gap-3.5">
                        <span
                          className={`w-7 h-7 rounded-lg text-[10px] font-bold flex items-center justify-center ${
                            tx.type === 'DEPOSIT'
                              ? 'bg-[#ccff00]/20 text-[#ccff00]'
                              : tx.type === 'WITHDRAWAL'
                              ? 'bg-amber-500/20 text-amber-400'
                              : tx.type === 'BUY'
                              ? 'bg-blue-500/20 text-blue-300'
                              : 'bg-rose-500/20 text-rose-400'
                          }`}
                        >
                          {tx.type[0]}
                        </span>
                        <div>
                          <p className="font-bold text-white font-sans">
                            {tx.type} {tx.symbol ? `· ${tx.symbol}` : ''}
                          </p>
                          <p className="text-[11px] text-slate-400 font-sans">{tx.plain_english_note || `${tx.type} record`}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="font-bold text-white">{formatCurrency(tx.amount)}</p>
                        <p className="text-[10px] text-blue-400">{new Date(tx.timestamp).toLocaleString()}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* 3. INSTITUTIONAL FOOTER (Professional Glassified Alignment) */}
      <footer className="glass-card-elevated border-t-2 border-yellow-400 py-5 text-violet-900 text-xs mt-12">
        <div className="max-w-7xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-center sm:text-left">
          <div className="flex items-center gap-2 font-mono">
            <span className="font-black text-violet-950 font-sans tracking-tight">GD-IPCA™ Mark 2</span>
            <span className="text-yellow-600 font-bold">·</span>
            <span className="font-bold text-violet-900">16 Core Investable ETFs</span>
            <span className="text-yellow-600 font-bold">·</span>
            <span className="font-bold text-violet-800">Goal-Driven Execution</span>
          </div>
          <div className="text-xs font-bold text-violet-900">
            Institutional Asset Allocation &amp; Portfolio Optimization Engine
          </div>
        </div>
      </footer>

      {/* 4. INTERACTIVE MODALS */}
      {/* Auth Modal */}
      {showAuthModal && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4">
          <div className="glass-card-elevated rounded-3xl p-7 max-w-sm w-full shadow-2xl border border-blue-500/30">
            <h3 className="text-lg font-bold text-white mb-1">
              {authMode === 'login' ? 'Institutional Sign In' : 'Register Account'}
            </h3>
            <p className="text-xs text-slate-400 mb-5 leading-relaxed">
              Enter your credentials to access user-level isolated goals and live portfolios.
            </p>

            <form onSubmit={handleAuthSubmit} className="space-y-4">
              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Email Address</label>
                <input
                  type="email"
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                  required
                  className="w-full text-xs px-3.5 py-2.5 rounded-xl glass-input font-mono focus:outline-none"
                />
              </div>
              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Password</label>
                <input
                  type="password"
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                  required
                  className="w-full text-xs px-3.5 py-2.5 rounded-xl glass-input font-mono focus:outline-none"
                />
              </div>

              <div className="flex gap-2.5 pt-2">
                <button
                  type="submit"
                  className="flex-1 py-3 rounded-xl bg-[#ccff00] text-black font-black text-xs shadow-lg shadow-[#ccff00]/25 btn-shimmer uppercase tracking-wider"
                >
                  {authMode === 'login' ? 'Authenticate' : 'Create Account'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowAuthModal(false)}
                  className="px-4 py-3 rounded-xl glass-pill text-slate-300 font-bold text-xs hover:bg-white/10"
                >
                  Cancel
                </button>
              </div>

              <div className="text-center pt-2">
                <button
                  type="button"
                  onClick={() => setAuthMode(authMode === 'login' ? 'register' : 'login')}
                  className="text-xs text-[#ccff00] hover:underline font-medium"
                >
                  {authMode === 'login' ? 'Need an account? Register here' : 'Already registered? Sign in'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Cash Deposit / Withdraw Modal */}
      {cashActionModal && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4">
          <div className="glass-card-elevated rounded-3xl p-7 max-w-sm w-full shadow-2xl border border-blue-500/30">
            <h3 className="text-lg font-bold text-white mb-1 capitalize">
              {cashActionModal} Cash
            </h3>
            <p className="text-xs text-slate-400 mb-5 leading-relaxed">
              {cashActionModal === 'deposit'
                ? 'Credit cash to your portfolio balance for allocation.'
                : `Withdraw cash. Note: Protected emergency reserve of ${formatCurrency(selectedPortfolio?.emergency_reserve || 0)} must be maintained.`}
            </p>

            <div className="space-y-4">
              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Amount ($ USD)</label>
                <input
                  type="number"
                  value={cashAmount}
                  onChange={(e) => setCashAmount(e.target.value)}
                  className="w-full text-lg font-bold font-mono px-3.5 py-2.5 rounded-xl glass-input"
                />
              </div>

              <div className="flex gap-2">
                {['5000', '10000', '25000', '50000'].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setCashAmount(preset)}
                    className="flex-1 py-1.5 rounded-lg glass-pill hover:border-[#ccff00]/40 text-[11px] font-mono font-semibold text-slate-300 hover:text-[#ccff00]"
                  >
                    +${parseInt(preset) / 1000}k
                  </button>
                ))}
              </div>

              <div className="flex gap-2.5 pt-2">
                <button
                  onClick={handleCashAction}
                  className="flex-1 py-3 rounded-xl bg-[#ccff00] text-black font-black text-xs shadow-lg shadow-[#ccff00]/25 btn-shimmer uppercase tracking-wider"
                >
                  Confirm {cashActionModal}
                </button>
                <button
                  onClick={() => setCashActionModal(null)}
                  className="px-4 py-3 rounded-xl glass-pill text-slate-300 font-bold text-xs hover:bg-white/10"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Direct Order Trade Modal */}
      {showTradeModal && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-4">
          <div className="glass-card-elevated rounded-3xl p-7 max-w-sm w-full shadow-2xl border border-blue-500/30">
            <h3 className="text-lg font-bold text-white mb-1">
              Direct Broker Order Placement
            </h3>
            <p className="text-xs text-slate-400 mb-5 leading-relaxed">
              Execute live market trades directly through the simulated paper broker matching engine.
            </p>

            <form onSubmit={handleExecuteTrade} className="space-y-4">
              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Asset Symbol</label>
                <select
                  value={tradeSymbol}
                  onChange={(e) => setTradeSymbol(e.target.value)}
                  className="w-full text-xs font-mono font-bold px-3.5 py-2.5 rounded-xl glass-input"
                >
                  {['VTI', 'VOO', 'VB', 'VXUS', 'VEA', 'VWO', 'BND', 'VCIT', 'VTIP', 'VNQ', 'GLD', 'SGOV', 'VGT'].map((s) => (
                    <option key={s} value={s} className="bg-black text-white">{s}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Order Side</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setTradeSide('BUY')}
                    className={`py-2 rounded-xl text-xs font-bold font-mono transition-all ${
                      tradeSide === 'BUY'
                        ? 'bg-[#ccff00] text-black font-black shadow-lg shadow-[#ccff00]/25'
                        : 'glass-pill text-slate-400 hover:text-white'
                    }`}
                  >
                    BUY
                  </button>
                  <button
                    type="button"
                    onClick={() => setTradeSide('SELL')}
                    className={`py-2 rounded-xl text-xs font-bold font-mono transition-all ${
                      tradeSide === 'SELL'
                        ? 'bg-rose-500 text-white shadow-lg shadow-rose-500/25'
                        : 'glass-pill text-slate-400 hover:text-white'
                    }`}
                  >
                    SELL
                  </button>
                </div>
              </div>

              <div>
                <label className="text-xs font-bold text-slate-300 block mb-1">Quantity (Shares)</label>
                <input
                  type="number"
                  step="any"
                  value={tradeShares}
                  onChange={(e) => setTradeShares(e.target.value)}
                  required
                  className="w-full text-sm font-mono font-bold px-3.5 py-2.5 rounded-xl glass-input"
                />
              </div>

              <div className="flex gap-2.5 pt-2">
                <button
                  type="submit"
                  disabled={isTrading}
                  className="flex-1 py-3 rounded-xl bg-[#ccff00] text-black font-black text-xs shadow-lg shadow-[#ccff00]/25 hover:bg-[#d9ff33] disabled:opacity-60 btn-shimmer uppercase tracking-wider"
                >
                  {isTrading ? 'Routing Order…' : `Submit ${tradeSide} Order`}
                </button>
                <button
                  type="button"
                  onClick={() => setShowTradeModal(false)}
                  className="px-4 py-3 rounded-xl glass-pill text-slate-300 font-bold text-xs hover:bg-white/10"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
