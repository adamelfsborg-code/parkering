const test = require('node:test');
const assert = require('node:assert');
const R = require('../src/rules.js');
const T = (y, m, d, h = 0, mi = 0) => R.toMin({ y, m, d, h, mi });

test('påsk och helgdagar 2026', () => {
  assert.deepStrictEqual(R.fromDayNum(R.easter(2026)), { y: 2026, m: 4, d: 5, wd: 0 });
  assert.ok(R.isHoliday(R.dayNum(2026, 4, 3)));   // långfredag
  assert.ok(R.isHoliday(R.dayNum(2026, 6, 20)));  // midsommardagen (lör)
  assert.ok(R.isHoliday(R.dayNum(2026, 10, 31))); // alla helgons dag
  assert.strictEqual(R.dayType(R.dayNum(2026, 11, 6)), 'wk');  // fre
  assert.strictEqual(R.dayType(R.dayNum(2026, 11, 7)), 'pre'); // lör
  assert.strictEqual(R.dayType(R.dayNum(2026, 12, 24)), 'pre'); // julafton (tor)
});

test('datumparkering: udda datum förbjudet på udda sida 00–06', () => {
  const n = R.datumNext(true, T(2026, 11, 5, 3));
  assert.ok(n.active);
  assert.strictEqual(R.datumNext(false, T(2026, 11, 5, 3)).active, false);
  assert.strictEqual(R.datumNext(true, T(2026, 11, 5, 6)).day, R.dayNum(2026, 11, 7));
  // utanför säsong: sommar → nästa förbud i november
  assert.strictEqual(R.fromDayNum(R.datumNext(true, T(2026, 6, 1, 12)).day).m, 11);
  // 15 maj ingår, 16 maj inte
  assert.ok(R.datumNext(true, T(2027, 5, 15, 2)).active);
  assert.strictEqual(R.datumNext(false, T(2027, 5, 16, 2)).active, false);
});

test('helg över flera nätter krockar alltid med någon sida', () => {
  const a = T(2026, 11, 6, 17), b = T(2026, 11, 8, 20); // fre → sön
  assert.ok(R.datumConflicts(true, a, b).length > 0);
  assert.ok(R.datumConflicts(false, a, b).length > 0);
  // en natt: mot lör 7 nov (udda) → jämna sidan fri
  assert.deepStrictEqual(R.datumConflicts(false, T(2026, 11, 6, 17), T(2026, 11, 7, 10)), []);
  // månadsskifte 31 → 1: båda udda, jämna sidan fri två nätter
  assert.deepStrictEqual(R.datumConflicts(false, T(2026, 12, 30, 18), T(2027, 1, 1, 10)), []);
});

test('24-timmarsregeln räknar inte lördag/söndag', () => {
  assert.strictEqual(R.counted24(T(2026, 11, 6, 18), T(2026, 11, 8, 20)), 6 * 60);
  assert.strictEqual(R.counted24(T(2026, 11, 6, 8), T(2026, 11, 9, 8)), 24 * 60);
  assert.ok(R.counted24(T(2026, 11, 9, 8), T(2026, 11, 10, 9)) > 24 * 60);
});

test('zonavgift', () => {
  const blue = { p: 6, wk: [9, 18], pre: [9, 15], all: false, max: null };
  // fre 17 → sön 20: fre 17–18 (1 h) + lör 9–15 (6 h) = 7 h * 6 kr
  assert.strictEqual(R.zoneFee(blue, T(2026, 11, 6, 17), T(2026, 11, 8, 20)).cost, 42);
  const red = { p: 15, wk: [9, 19], pre: [9, 15], all: false, max: 2 };
  assert.ok(R.zoneFee(red, T(2026, 11, 9, 9), T(2026, 11, 9, 12)).maxExceeded);
  assert.ok(!R.zoneFee(red, T(2026, 11, 9, 17), T(2026, 11, 10, 8)).maxExceeded);
});

test('parkeringshus', () => {
  const mob = { type: 'mobility', peak: 8, offpeak: 6, peakFrom: 6, peakTo: 19 };
  assert.strictEqual(R.facilityCost(mob, T(2026, 11, 6, 17), T(2026, 11, 6, 21)), 2 * 8 + 2 * 6);
  const aimo = { type: 'aimo', first2: 24, after: 25, cap24: 155 };
  assert.strictEqual(R.facilityCost(aimo, T(2026, 11, 6, 17), T(2026, 11, 6, 20)), 73);
  assert.strictEqual(R.facilityCost(aimo, T(2026, 11, 6, 17), T(2026, 11, 8, 20)), 155 * 2 + 73);
  assert.ok(!R.openOk([6, 22], T(2026, 11, 6, 23), T(2026, 11, 8, 20)));
});
