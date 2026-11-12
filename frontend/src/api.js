/**
 * GD-IPCA Mark 2 API Client
 * Full backend wiring for Authentication, Goals, Monte Carlo, Portfolios,
 * Holdings, Transactions, Orders, Rebalance, and Market Data.
 * Falls back to local engine gracefully if backend is offline.
 */

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const TOKEN_KEY = "gdipca_auth_token";

export function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {}
}

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const token = getStoredToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const errJson = await res.json();
      errorDetail = errJson.detail || errJson.message || JSON.stringify(errJson);
    } catch {
      const text = await res.text();
      if (text) errorDetail = text;
    }
    throw new Error(`API ${res.status}: ${errorDetail}`);
  }
  return res.json();
}

// ---------------- Health & Diagnostics ----------------
export async function healthCheck() {
  return request("/api/v1/health");
}

// ---------------- Authentication ----------------
export async function loginUser(email, password) {
  const res = await request("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (res.access_token) {
    setStoredToken(res.access_token);
  }
  return res;
}

export async function registerUser(email, password, displayName) {
  const res = await request("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (res.access_token) {
    setStoredToken(res.access_token);
  }
  return res;
}

export async function fetchCurrentUser() {
  return request("/api/v1/auth/me");
}

export function logoutUser() {
  setStoredToken(null);
}

// ---------------- Intent & Goals ----------------
export async function fetchSeeds() {
  return request("/api/v1/intent/seeds");
}

export async function compileIntent(rawText, saveGoal = false) {
  return request("/api/v1/intent/compile", {
    method: "POST",
    body: JSON.stringify({ raw_text: rawText, save_goal: saveGoal }),
  });
}

export async function fetchUserGoals() {
  return request("/api/v1/intent/goals");
}

// ---------------- Simulation ----------------
export async function runMonteCarlo(payload) {
  return request("/api/v1/simulate/monte-carlo", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------- Portfolios & Holdings ----------------
export async function fetchPortfolios() {
  return request("/api/v1/portfolios");
}

export async function createPortfolio(data) {
  return request("/api/v1/portfolios", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function fetchPortfolioDetail(portfolioId) {
  return request(`/api/v1/portfolios/${portfolioId}`);
}

export async function depositCash(portfolioId, amount, note = "") {
  return request(`/api/v1/portfolios/${portfolioId}/deposit`, {
    method: "POST",
    body: JSON.stringify({ amount, note }),
  });
}

export async function withdrawCash(portfolioId, amount, note = "") {
  return request(`/api/v1/portfolios/${portfolioId}/withdraw`, {
    method: "POST",
    body: JSON.stringify({ amount, note }),
  });
}

export async function placeTrade(portfolioId, { symbol, side, quantity, orderType = "MARKET" }) {
  return request(`/api/v1/portfolios/${portfolioId}/trade`, {
    method: "POST",
    body: JSON.stringify({ symbol, side, quantity, order_type: orderType }),
  });
}

export async function fetchTransactions(portfolioId) {
  return request(`/api/v1/portfolios/${portfolioId}/transactions`);
}

export async function fetchOrders(portfolioId) {
  return request(`/api/v1/portfolios/${portfolioId}/orders`);
}

// ---------------- Rebalancing ----------------
export async function executeRebalance({ portfolioId, goalId, autoExecute = false, thresholdPct = 0.02 }) {
  return request("/api/v1/rebalance/execute", {
    method: "POST",
    body: JSON.stringify({
      portfolio_id: portfolioId,
      goal_id: goalId,
      auto_execute: autoExecute,
      threshold_pct: thresholdPct,
    }),
  });
}

// ---------------- Market Data ----------------
export async function fetchMarketQuote(symbol) {
  return request(`/api/v1/market/quote/${symbol}`);
}

export async function fetchUniverseQuotes() {
  return request("/api/v1/market/universe");
}

export async function fetchHistoricalBars(symbol, limit = 90) {
  return request(`/api/v1/market/history/${symbol}?limit=${limit}`);
}

// ---------------- PayPal Developer Platform ----------------
export async function fetchPayPalStatus() {
  return request("/api/v1/paypal/status");
}

export async function createPayPalOrder(payload) {
  return request("/api/v1/paypal/orders/create", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function capturePayPalOrder(orderId) {
  return request(`/api/v1/paypal/orders/${orderId}/capture`, {
    method: "POST",
  });
}

export async function createPayPalPayout(payload) {
  return request("/api/v1/paypal/payouts/create", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchPayPalRecords() {
  return request("/api/v1/paypal/records");
}

// ---------------- AI Agentic Commerce ----------------
export async function fetchAgentTools() {
  return request("/api/v1/agent/tools");
}

export async function planAgentAction(payload) {
  return request("/api/v1/agent/plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function executeAgentPayPalAction(payload) {
  return request("/api/v1/agent/execute-paypal", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export { API_BASE };
