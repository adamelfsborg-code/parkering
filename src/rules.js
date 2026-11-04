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

  // ---------- Säsonger och tidsfönster ----------
  // m = [månad, dag, månad, dag] (kan gå över nyår), null = hela året
  const monthOk = (n, m) => {
    if (!m) return true;
    const x = fromDayNum(n), md = x.m * 100 + x.d, a = m[0] * 100 + m[1], b = m[2] * 100 + m[3];
    return a <= b ? md >= a && md <= b : md >= a || md <= b;
  };

  // ---------- Datumparkering ----------
  // Allmän regel i Gävle (2180 2025:233): kl 00–06, 1 nov–15 maj. Enskilda föreskrifter kan ha
  // egna tider (ofta 00–08, 1 okt–15 maj) som då gäller på den sträckan.
  const GENERAL = { f: 0, t: 360, m: [11, 1, 5, 15] };
  const inSeason = (m, d) => monthOk(dayNum(2001, m, d), GENERAL.m);
  const windowsFor = (oddSide, n, spec = GENERAL) => {
    const x = fromDayNum(n);
    if (!monthOk(n, spec.m || GENERAL.m) || (x.d % 2 === 1) !== oddSide) return null;
    const end = spec.t > spec.f ? spec.t : spec.t + DAY;
    return [n * DAY + spec.f, n * DAY + end];
  };

  // Aktivt eller nästa förbudsfönster för en sida vid tidpunkt t, över flera regeluppsättningar
  function datumNext(oddSide, t, specs = [GENERAL]) {
    const today = Math.floor(t / DAY);
    let best = null;
    for (const spec of specs) {
      for (let n = today - 1; n < today + 400; n++) {
        const w = windowsFor(oddSide, n, spec);
        if (w && w[1] > t) {
          const cand = { day: n, active: w[0] <= t, startsIn: w[0] - t, f: spec.f, t: spec.t };
          if (!best || cand.startsIn < best.startsIn) best = cand;
          break;
        }
      }
    }
    return best;
  }

  // Alla förbudsfönster som överlappar [a, b)
  function datumConflicts(oddSide, a, b, specs = [GENERAL]) {
    const out = new Set();
    for (const spec of specs) {
      for (let n = Math.floor(a / DAY) - 1; n * DAY < b; n++) {
        const w = windowsFor(oddSide, n, spec);
        if (w && w[0] < b && w[1] > a) out.add(n);
      }
    }
    return [...out].sort((x, y) => x - y);
  }

  // ---------- Tidsfönster i lokala trafikföreskrifter ----------
  // sched = [{ d: ['wk'|'pre'|'hol'|'d0'..'d6'|'helgfri'] | null, f, t, m }], null = alltid
  function dayMatch(n, codes) {
    if (!codes || !codes.length) return true;
    const helgfri = codes.includes('helgfri'), ty = dayType(n), wd = fromDayNum(n).wd;
    return codes.some(c => c === 'helgfri' ? false
      : c[0] === 'd' ? +c[1] === wd && !(helgfri && isHoliday(n))
      : c === ty);
  }
  function schedActive(sched, t) {
    if (!sched) return true;
    const n = Math.floor(t / DAY), mm = t - n * DAY;
    return sched.some(w => {
      if (w.f < w.t) return mm >= w.f && mm < w.t && dayMatch(n, w.d) && monthOk(n, w.m);
      return (mm >= w.f && dayMatch(n, w.d) && monthOk(n, w.m)) || (mm < w.t && dayMatch(n - 1, w.d) && monthOk(n - 1, w.m));
    });
  }
  // Minuter tills fönstret börjar (inom horisonten), annars null
  function schedNext(sched, t, horizon) {
    if (!sched) return 0;
    for (let x = Math.ceil((t + 1) / 15) * 15; x <= t + horizon; x += 15) if (schedActive(sched, x)) return x - t;
    return null;
  }
  // Överlapp med [a, b): { any, longest } i minuter (provas var 5:e minut)
  function schedOverlap(sched, a, b) {
    if (!sched) return { any: b > a, longest: b - a, total: b - a };
    let any = false, run = 0, longest = 0, total = 0;
    for (let x = a; x < b; x += 5) {
      if (schedActive(sched, x)) { any = true; run += 5; total += 5; longest = Math.max(longest, run); } else run = 0;
    }
    return { any, longest, total };
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
    DAY, GENERAL, dayNum, fromDayNum, toMin, fromMin, easter, holidays, isHoliday, dayType, inSeason, monthOk,
    datumNext, datumConflicts, dayMatch, schedActive, schedNext, schedOverlap, counted24, zoneFee, facilityCost, openOk,
  };
  if (typeof module !== 'undefined') module.exports = root.Rules;
})(typeof window !== 'undefined' ? window : globalThis);
