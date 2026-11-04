// Parkeringsregler för Gävle. Ren logik utan DOM så att den kan testas med node.
// Tider räknas i "lokala minuter": dagnummer * 1440 + minut på dygnet (svensk tid).
(function (root) {
  const DAY = 1440;

  const dayNum = (y, m, d) => Math.round(Date.UTC(y, m - 1, d) / 864e5);
  const fromDayNum = n => {
    const t = new Date(n * 864e5);
    return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate(), wd: t.getUTCDay() };
  };
  const toMin = p => dayNum(p.y, p.m, p.d) * DAY + p.h * 60 + (p.mi || 0);
  const fromMin = t => ({ ...fromDayNum(Math.floor(t / DAY)), h: Math.floor((t % DAY) / 60), mi: t % 60 });

  // ---------- Helgdagar ----------
  function easter(y) {
    const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4;
    const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7;
    const m = Math.floor((a + 11 * h + 22 * l) / 451), month = Math.floor((h + l - 7 * m + 114) / 31);
    return dayNum(y, month, ((h + l - 7 * m + 114) % 31) + 1);
  }
  const satBetween = (y, m, d1) => { for (let d = d1; d < d1 + 7; d++) { const n = dayNum(y, m, d); if (fromDayNum(n).wd === 6) return n; } };
  const holidayCache = {};
  function holidays(y) {
    if (holidayCache[y]) return holidayCache[y];
    const e = easter(y);
    return (holidayCache[y] = new Set([
      dayNum(y, 1, 1), dayNum(y, 1, 6), e - 2, e, e + 1, dayNum(y, 5, 1), e + 39, dayNum(y, 6, 6), e + 49,
      satBetween(y, 6, 20), satBetween(y, 10, 31), dayNum(y, 12, 25), dayNum(y, 12, 26),
    ]));
  }
  const isHoliday = n => { const x = fromDayNum(n); return x.wd === 0 || holidays(x.y).has(n); };
  // 'hol' = sön-/helgdag, 'pre' = vardag före sön-/helgdag, 'wk' = övrig vardag
  const dayType = n => isHoliday(n) ? 'hol' : (isHoliday(n + 1) ? 'pre' : 'wk');

  // ---------- Datumparkering (Gävle: 1 nov–15 maj, 00–06) ----------
  const inSeason = (m, d) => m >= 11 || m <= 4 || (m === 5 && d <= 15);
  const windowsFor = (oddSide, n) => {
    const x = fromDayNum(n);
    return inSeason(x.m, x.d) && (x.d % 2 === 1) === oddSide ? [n * DAY, n * DAY + 360] : null;
  };

  // Aktivt eller nästa förbudsfönster för en sida vid tidpunkt t
  function datumNext(oddSide, t) {
    const today = Math.floor(t / DAY);
    for (let n = today; n < today + 400; n++) {
      const w = windowsFor(oddSide, n);
      if (w && w[1] > t) return { day: n, active: w[0] <= t, startsIn: w[0] - t };
    }
    return null;
  }

  // Alla förbudsfönster som överlappar [a, b)
  function datumConflicts(oddSide, a, b) {
    const out = [];
    for (let n = Math.floor(a / DAY); n * DAY < b; n++) {
      const w = windowsFor(oddSide, n);
      if (w && w[0] < b && w[1] > a) out.push(n);
    }
    return out;
  }

  // ---------- 24-timmarsregeln ----------
  // Tid räknas bara på vardagar som inte är dag före sön-/helgdag.
  function counted24(a, b) {
    let mins = 0;
    for (let n = Math.floor(a / DAY); n * DAY < b; n++) {
      if (dayType(n) !== 'wk') continue;
      mins += Math.max(0, Math.min(b, (n + 1) * DAY) - Math.max(a, n * DAY));
    }
    return mins;
  }

  // ---------- Avgiftszon på gata ----------
  // Returnerar { cost, paidMin, maxExceeded }
  function zoneFee(z, a, b) {
    let paid = 0, run = 0, longest = 0, lastEnd = null;
    for (let n = Math.floor(a / DAY); n * DAY < b; n++) {
      const ty = dayType(n);
      let hrs = null;
      if (z.all) hrs = [0, 24];
      else if (ty === 'wk') hrs = z.wk;
      else if (ty === 'pre') hrs = z.pre;
      if (!hrs) continue;
      const s = Math.max(a, n * DAY + hrs[0] * 60), e = Math.min(b, n * DAY + hrs[1] * 60);
      if (e <= s) continue;
      paid += e - s;
      run = lastEnd === s ? run + (e - s) : e - s;
      lastEnd = e;
      longest = Math.max(longest, run);
    }
    return { cost: Math.round(paid / 60 * z.p), paidMin: paid, maxExceeded: !!z.max && longest > z.max * 60 };
  }

  // ---------- Parkeringshus ----------
  function facilityCost(tariff, a, b) {
    if (!tariff) return null;
    if (tariff.type === 'mobility') {
      let cost = 0;
      for (let t = a; t < b; t += 60) {
        const x = fromMin(t), weekday = x.wd >= 1 && x.wd <= 5;
        const peak = weekday && x.h >= tariff.peakFrom && x.h < tariff.peakTo;
        cost += (peak ? tariff.peak : tariff.offpeak) * Math.min(60, b - t) / 60;
      }
      return Math.round(cost);
    }
    if (tariff.type === 'aimo') {
      const hours = Math.ceil((b - a) / 60), full = Math.floor(hours / 24), rest = hours % 24;
      const restCost = Math.min(tariff.cap24, tariff.first2 * Math.min(rest, 2) + tariff.after * Math.max(0, rest - 2));
      return full * tariff.cap24 + restCost;
    }
    return null;
  }

  // Ligger in- och utfart inom öppettiderna?
  function openOk(open, a, b) {
    if (!open || (open[0] === 0 && open[1] === 24)) return true;
    const h = t => (t % DAY) / 60;
    return h(a) >= open[0] && h(a) <= open[1] && h(b) >= open[0] && h(b) <= open[1];
  }

  root.Rules = {
    DAY, dayNum, fromDayNum, toMin, fromMin, easter, holidays, isHoliday, dayType, inSeason,
    datumNext, datumConflicts, counted24, zoneFee, facilityCost, openOk,
  };
  if (typeof module !== 'undefined') module.exports = root.Rules;
})(typeof window !== 'undefined' ? window : globalThis);
