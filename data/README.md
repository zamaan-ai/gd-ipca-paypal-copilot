# GD-IPCA Dataset v1.0

Self-contained datasets for the Goal-Driven Intent-to-Portfolio Compilation Engine.

## Files

| File | Description |
|------|-------------|
| `assets.csv` | Investable universe (16 instruments across Equity, Fixed Income, Alternatives, Cash) |
| `market_parameters.json` | Expected returns, volatilities, higher moments, full correlation matrix, regime probabilities, simulation defaults |
| `sample_intents.json` | 5 realistic goal ASTs matching the exact schema from SPEC-GDIPCA-FULL §4.1 |
| `historical_prices.csv` | Synthetic but realistic 5-year daily price series (correlated GBM) for charting & backtesting |
| `README.md` | This file |

## Asset Classes Covered
- **US Equity**: Broad (VTI), Large (VOO), Small (VB), Tech (VGT), Health Care (VHT)
- **International Equity**: Total Int'l (VXUS), Developed (VEA), Emerging (VWO)
- **Fixed Income**: US Aggregate (BND), Corporate (VCIT), TIPS (VTIP), Int'l Bonds (BNDX)
- **Alternatives**: REITs (VNQ), Gold (GLD)
- **Cash Equivalents**: T-Bills (BIL, SGOV)

## Key Design Choices
- Correlation matrix is positive-definite and realistic (equities highly correlated, bonds low/negative, gold low, cash near-zero).
- Regime switching (Normal / Bull / Bear / Crisis) ready for Monte Carlo.
- Student's t-copula parameters present for fat-tail shocks.
- All sample intents include `guaranteed_reserve`, `confidence_threshold`, and `utility_function_params` exactly as specified in the architecture document.
- Inflation default = 2.8% (matches utility params in the house example).

## Usage Notes
- Monte Carlo should use `market_parameters.json` → `assets` + `correlation_matrix` + `regime_parameters`.
- Intent Compiler should emit objects whose shape matches the entries in `sample_intents.json`.
- Frontend can load `sample_intents.json` for preset goals and `historical_prices.csv` for any price-based charts.
- Liquidity score (1–10) and expense ratios are included for future tax-aware / cost-aware optimization.

## Version
Aligned with SPEC-GDIPCA-FULL Version 3.4.0-RELEASE
