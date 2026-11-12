"""
Stochastic Monte Carlo engine for GD-IPCA.
Uses market_parameters.json: expected returns, vols, correlation, regime switching.
"""
from __future__ import annotations
import numpy as np
from typing import Any
from app.core.config import get_market_parameters


def _cholesky_psd(corr: np.ndarray) -> np.ndarray:
    """Ensure positive-definite and return Cholesky factor."""
    corr = (corr + corr.T) / 2
    np.fill_diagonal(corr, 1.0)
    eig = np.linalg.eigvalsh(corr)
    if eig.min() < 1e-8:
        corr = corr + np.eye(len(corr)) * (1e-6 - eig.min())
    return np.linalg.cholesky(corr)


def run_monte_carlo(
    time_horizon_years: float,
    target_valuation: float,
    risk_profile_index: float,
    guaranteed_reserve: float = 0.0,
    confidence_threshold: float = 0.90,
    n_paths: int = 5000,
    seed: int | None = 42,
) -> dict[str, Any]:
    """
    Vectorized Monte Carlo with regime switching.
    Returns trajectory percentiles, success probability, allocation, and meta.
    """
    params = get_market_parameters()
    assets = params["assets"]
    order = params["correlation_matrix"]["assets_order"]
    corr = np.array(params["correlation_matrix"]["matrix"], dtype=float)
    regimes = params["regime_parameters"]
    rf = params.get("risk_free_rate_annual", 0.042)

    if seed is not None:
        np.random.seed(seed)

    # Map risk index (0–10) → equity weight
    risk = max(0.0, min(10.0, risk_profile_index)) / 10.0
    equity_w = float(np.clip(0.20 + risk * 0.65, 0.15, 0.85))
    bond_w = 1.0 - equity_w

    # Build portfolio from asset classes
    eq_ids = [a for a in order if a.startswith("EQ-") or a.startswith("ALT-")]
    fi_ids = [a for a in order if a.startswith("FI-") or a.startswith("CASH-")]

    def class_stats(ids: list[str]) -> tuple[float, float]:
        rets = [assets[i]["expected_return_annual"] for i in ids if i in assets]
        vols = [assets[i]["volatility_annual"] for i in ids if i in assets]
        return (float(np.mean(rets)), float(np.mean(vols))) if rets else (0.05, 0.12)

    eq_mu, eq_sig = class_stats(eq_ids)
    fi_mu, fi_sig = class_stats(fi_ids)

    # Portfolio mu/sigma (simple 2-asset with low corr)
    port_mu = equity_w * eq_mu + bond_w * fi_mu
    port_sig = np.sqrt(
        (equity_w ** 2) * (eq_sig ** 2)
        + (bond_w ** 2) * (fi_sig ** 2)
        + 2 * equity_w * bond_w * eq_sig * fi_sig * 0.15
    )

    years = int(np.ceil(time_horizon_years))
    # Starting capital heuristic + annual contribution
    start = max(target_valuation * 0.10, guaranteed_reserve * 1.2)
    annual_contrib = max(0.0, (target_valuation - start) / max(years, 1) * 0.90)

    # Regime probabilities
    reg_names = list(regimes.keys())
    reg_probs = np.array([regimes[r]["probability"] for r in reg_names])
    reg_probs = reg_probs / reg_probs.sum()

    paths = np.zeros((n_paths, years + 1))
    paths[:, 0] = start

    for t in range(1, years + 1):
        # Draw regime per path
        regime_idx = np.random.choice(len(reg_names), size=n_paths, p=reg_probs)
        ret_mult = np.array([regimes[reg_names[i]]["return_multiplier"] for i in regime_idx])
        vol_mult = np.array([regimes[reg_names[i]]["vol_multiplier"] for i in regime_idx])

        # Student-t like fat tails via mixture: mostly normal, occasional large shock
        z = np.random.normal(0, 1, n_paths)
        fat = np.random.standard_t(5, n_paths)
        shock = np.where(np.random.random(n_paths) < 0.12, fat * 0.7, z)

        period_ret = (port_mu * ret_mult) + (port_sig * vol_mult) * shock
        # Clip extreme one-year moves
        period_ret = np.clip(period_ret, -0.55, 0.80)

        paths[:, t] = np.maximum(0.0, paths[:, t - 1] * (1.0 + period_ret) + annual_contrib)

    # Percentiles
    percentiles = []
    for t in range(years + 1):
        col = paths[:, t]
        percentiles.append({
            "year": t,
            "p10": float(np.percentile(col, 10)),
            "p25": float(np.percentile(col, 25)),
            "median": float(np.percentile(col, 50)),
            "p75": float(np.percentile(col, 75)),
            "p90": float(np.percentile(col, 90)),
            "target": target_valuation,
        })

    final = paths[:, -1]
    success = float(np.mean(final >= target_valuation))
    median_final = float(np.median(final))

    # Suggested allocation (normalized)
    allocation = {
        "us_equity": round(equity_w * 0.55, 3),
        "intl_equity": round(equity_w * 0.25, 3),
        "us_bonds": round(bond_w * 0.50, 3),
        "tips": round(bond_w * 0.20, 3),
        "cash": round(bond_w * 0.30, 3),
        "alternatives": round(equity_w * 0.20, 3),
    }
    total = sum(allocation.values())
    allocation = {k: round(v / total, 3) for k, v in allocation.items()}

    # Max drawdown proxy (path-wise)
    peak = np.maximum.accumulate(paths, axis=1)
    dd = (peak - paths) / np.maximum(peak, 1e-9)
    max_dd_p95 = float(np.percentile(dd.max(axis=1), 95))

    return {
        "trajectory_percentiles": percentiles,
        "success_probability": success,
        "median_final_value": median_final,
        "suggested_allocation": allocation,
        "equity_weight": round(equity_w, 3),
        "bond_weight": round(bond_w, 3),
        "port_mu": round(port_mu, 4),
        "port_sigma": round(port_sig, 4),
        "start_capital": round(start, 2),
        "annual_contribution": round(annual_contrib, 2),
        "max_drawdown_p95": round(max_dd_p95, 4),
        "meets_confidence": success >= confidence_threshold,
        "engine_meta": {
            "runs": n_paths,
            "years": years,
            "regimes": reg_names,
            "note": "Regime-switching GBM with Student-t fat-tail shocks",
        },
    }
