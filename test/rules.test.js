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

test('tidsfönster i föreskrifter', () => {
  // vardagar utom dag före helgdag 9–19 (fre 6 nov 2026 är vanlig vardag, lör 7 nov är dag före söndag)
  const s = [{ d: ['wk'], f: 540, t: 1140 }, { d: ['pre'], f: 540, t: 900 }];
  assert.ok(R.schedActive(s, T(2026, 11, 6, 10)));
  assert.ok(!R.schedActive(s, T(2026, 11, 6, 20)));
  assert.ok(R.schedActive(s, T(2026, 11, 7, 14)));
  assert.ok(!R.schedActive(s, T(2026, 11, 7, 16)));
  assert.ok(!R.schedActive(s, T(2026, 11, 8, 12)));  // söndag
  // över midnatt 22–04 alla dagar
  const n = [{ d: null, f: 1320, t: 240 }];
  assert.ok(R.schedActive(n, T(2026, 11, 6, 23)) && R.schedActive(n, T(2026, 11, 7, 3)) && !R.schedActive(n, T(2026, 11, 7, 5)));
  // helgfri måndag 8–12
  const m = [{ d: ['helgfri', 'd1'], f: 480, t: 720 }];
  assert.ok(R.schedActive(m, T(2026, 11, 9, 9)));
  assert.ok(!R.schedActive(m, T(2026, 4, 6, 9)));  // annandag påsk
  assert.strictEqual(R.schedNext(s, T(2026, 11, 6, 7), 12 * 60), 120);
  assert.strictEqual(R.schedOverlap(s, T(2026, 11, 6, 8), T(2026, 11, 6, 12)).longest, 180);
});

test('egen datumregel på sträcka (00–08, 1 okt–15 maj)', () => {
  const own = { f: 0, t: 480, m: [10, 1, 5, 15] };
  // 15 okt 2026 är udda: allmän regel gäller inte än (säsong från 1 nov), egen regel gör det
  assert.strictEqual(R.datumNext(true, T(2026, 10, 15, 3)).active, false);
  assert.ok(R.datumNext(true, T(2026, 10, 15, 7), [R.GENERAL, own]).active);
  assert.ok(R.datumConflicts(true, T(2026, 11, 5, 6, 30), T(2026, 11, 5, 9), [R.GENERAL, own]).length === 1);
  assert.ok(R.datumConflicts(true, T(2026, 11, 5, 6, 30), T(2026, 11, 5, 9)).length === 0);
});
