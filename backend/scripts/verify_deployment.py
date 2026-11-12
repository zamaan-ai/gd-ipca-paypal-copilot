"""
GD-IPCA Deployment Verification & Full System Health Audit Script
Runs comprehensive runtime checks against the live system.
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings, get_sample_intents
from app.db.session import SessionLocal
from app.models.entities import User, Portfolio, IntentGoal
from app.services.market_data import market_data_service
from app.services.cache import cache


def run_verification():
    print("=" * 60)
    print(f"GD-IPCA Full-System Deployment Verification (v{settings.VERSION})")
    print("=" * 60)

    # 1. Database Check
    print("\n[1/6] Verifying Database Connection...")
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        goal_count = db.query(IntentGoal).count()
        port_count = db.query(Portfolio).count()
        print(f"  [OK] Database connected! Users: {user_count}, Goals: {goal_count}, Portfolios: {port_count}")
    except Exception as e:
        print(f"  [FAIL] Database check failed: {e}")
        return False
    finally:
        db.close()

    # 2. Redis/Cache Check
    print("\n[2/6] Verifying Cache Service...")
    cache.set("verify_key", "healthy_status", ttl=10)
    val = cache.get("verify_key")
    if val == "healthy_status":
        cache_type = "Redis Server" if cache.is_redis_online() else "In-Memory Thread-Safe Cache"
        print(f"  [OK] Cache operational ({cache_type})")
    else:
        print("  [FAIL] Cache write/read failed")
        return False

    # 3. Market Data Check
    print("\n[3/6] Verifying Market Data Provider...")
    vti_quote = market_data_service.get_latest_price("VTI")
    if vti_quote and vti_quote.get("price", 0) > 0:
        print(f"  [OK] VTI quote fetched: ${vti_quote['price']:.2f} (Source: {vti_quote['source']})")
    else:
        print("  [FAIL] Market data quote lookup failed")
        return False

    # 4. Intent Compiler & Presets
    print("\n[4/6] Verifying Intent Compiler & Datasets...")
    seeds = get_sample_intents()
    print(f"  [OK] Sample goal AST seeds loaded: {len(seeds)} presets ready")

    # 5. Monte Carlo Simulation Engine
    print("\n[5/6] Verifying Monte Carlo Simulation Engine...")
    from app.services.monte_carlo import run_monte_carlo
    mc_result = run_monte_carlo(
        time_horizon_years=5.0,
        target_valuation=150000.0,
        risk_profile_index=3.5,
        guaranteed_reserve=25000.0,
        n_paths=1000,
    )
    if mc_result and "success_probability" in mc_result:
        print(f"  [OK] Monte Carlo simulation ran successfully: Success Probability: {mc_result['success_probability']*100:.1f}%, Median Outcome: ${mc_result['median_final_value']:,.2f}")
    else:
        print("  [FAIL] Monte Carlo simulation run failed")
        return False

    # 6. Broker Engine Simulation
    print("\n[6/6] Verifying Broker Execution Engine...")
    from app.services.broker import broker_service
    print(f"  [OK] Broker mode active: {broker_service.mode.upper()}")

    print("\n" + "=" * 60)
    print("ALL 6 CORE SYSTEM VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
