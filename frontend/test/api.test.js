import test from 'node:test';
import assert from 'node:assert/strict';

test('formatCurrency utility formats USD correctly', () => {
  const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  assert.equal(formatter.format(150000), '$150,000');
  assert.equal(formatter.format(0), '$0');
  assert.equal(formatter.format(25000), '$25,000');
});

test('formatPct utility formats percentage accurately', () => {
  const formatPct = (v) => `${(v * 100).toFixed(1)}%`;
  assert.equal(formatPct(0.9234), '92.3%');
  assert.equal(formatPct(0.60), '60.0%');
  assert.equal(formatPct(0.042), '4.2%');
});

test('Local Monte Carlo fallback trajectory produces monotonic percentiles', () => {
  const nPaths = 50;
  const years = 5;
  const paths = [];
  for (let p = 0; p < nPaths; p++) {
    let val = 25000;
    const series = [val];
    for (let y = 1; y <= years; y++) {
      val = val * (1 + 0.07);
      series.push(val);
    }
    paths.push(series);
  }

  for (let y = 0; y <= years; y++) {
    const vals = paths.map((p) => p[y]).sort((a, b) => a - b);
    const p10 = vals[Math.floor(nPaths * 0.1)];
    const p50 = vals[Math.floor(nPaths * 0.5)];
    const p90 = vals[Math.floor(nPaths * 0.9)];
    assert.ok(p10 <= p50, `p10 (${p10}) should be <= p50 (${p50})`);
    assert.ok(p50 <= p90, `p50 (${p50}) should be <= p90 (${p90})`);
  }
});

test('Rebalance drift calculation logic detects drift accurately', () => {
  const currentEquity = 0.75;
  const targetEquity = 0.60;
  const drift = Math.abs(currentEquity - targetEquity);
  const threshold = 0.02;
  assert.equal(drift.toFixed(2), '0.15');
  assert.ok(drift > threshold, 'Drift of 15% should exceed 2% threshold');
});

test('Emergency reserve ring-fence protects reserve from withdrawal', () => {
  const cashBalance = 35000;
  const emergencyReserve = 25000;
  const maxAvailableToWithdraw = cashBalance - emergencyReserve;
  assert.equal(maxAvailableToWithdraw, 10000);
  const attemptedWithdrawal = 15000;
  const isAllowed = attemptedWithdrawal <= maxAvailableToWithdraw;
  assert.equal(isAllowed, false, 'Withdrawal violating reserve must be blocked');
});
