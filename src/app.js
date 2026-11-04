(() => {
  const R = window.Rules;
  const APP = window.APP || {};
  const D = JSON.parse(document.getElementById('data').textContent);
  const HW = D.hw;
  document.body.classList.toggle('tiles', !!APP.tiles);
  const LAT0 = 60.67, KX = 111320 * Math.cos(LAT0 * Math.PI / 180), KY = 110540;
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // ---------- Tid ----------
  const WD = ['sön', 'mån', 'tis', 'ons', 'tor', 'fre', 'lör'];
  const MON = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];
  const fmt = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Stockholm', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  function nowMin() {
    const p = Object.fromEntries(fmt.formatToParts(new Date()).map(x => [x.type, x.value]));
    return R.toMin({ y: +p.year, m: +p.month, d: +p.day, h: +p.hour % 24, mi: +p.minute });
  }
  const pad = x => String(x).padStart(2, '0');
  const dayLabel = n => { const t = R.fromDayNum(n); return `${WD[t.wd]} ${t.d} ${MON[t.m - 1]}`; };
  const timeLabel = t => { const x = R.fromMin(t); return `${dayLabel(Math.floor(t / R.DAY))} kl ${pad(x.h)}:${pad(x.mi)}`; };
  const toInput = t => { const x = R.fromMin(t); return `${x.y}-${pad(x.m)}-${pad(x.d)}T${pad(x.h)}:${pad(x.mi)}`; };
  const fromInput = v => { if (!v) return null; const [d, tm] = v.split('T'); const [y, m, dd] = d.split('-').map(Number); const [h, mi] = tm.split(':').map(Number); return R.toMin({ y, m, d: dd, h, mi }); };
  const parity = n => (R.fromDayNum(n).d % 2 ? 'udda' : 'jämnt');
  const durLabel = m => { const h = Math.round(m / 60); return h < 48 ? `${h} h` : `${Math.floor(h / 24)} d ${h % 24} h`; };

  // ---------- Geometri ----------
  const decode = a => { const out = []; let la = 0, lo = 0; for (let i = 0; i < a.length; i += 2) { la += a[i]; lo += a[i + 1]; out.push([la / 1e5, lo / 1e5]); } return out; };
  const xyOf = ([la, lo]) => [lo * KX, la * KY];
  const llOf = ([x, y]) => [y / KY, x / KX];
  function offset(xy, dist) {
    const n = xy.length, out = [];
    const nrm = (a, b) => { const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1; return [-dy / l, dx / l]; };
    for (let i = 0; i < n; i++) {
      const n1 = i > 0 ? nrm(xy[i - 1], xy[i]) : null, n2 = i < n - 1 ? nrm(xy[i], xy[i + 1]) : null;
      let nx, ny;
      if (n1 && n2) {
        nx = n1[0] + n2[0]; ny = n1[1] + n2[1];
        const l = Math.hypot(nx, ny) || 1; nx /= l; ny /= l;
        const k = 1 / Math.max(nx * n1[0] + ny * n1[1], 0.5); nx *= k; ny *= k;
      } else [nx, ny] = n1 || n2;
      out.push([xy[i][0] + nx * dist, xy[i][1] + ny * dist]);
    }
    return out;
  }
  function nearestOn(p, xy) {
    let best = { d: Infinity, pt: xy[0] };
    for (let i = 0; i < xy.length - 1; i++) {
      const a = xy[i], b = xy[i + 1], dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
      const t = l2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2)) : 0;
      const c = [a[0] + t * dx, a[1] + t * dy], d = Math.hypot(p[0] - c[0], p[1] - c[1]);
      if (d < best.d) best = { d, pt: c };
    }
    return best;
  }
  const distM = (a, b) => { const p = xyOf(a), q = xyOf(b); return Math.hypot(p[0] - q[0], p[1] - q[1]); };
  const walkLabel = m => m < 950 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1).replace('.', ',')} km`;
  const walkMin = m => Math.max(1, Math.round(m * 1.3 / 75));

  // ---------- Zoner ----------
  const ZCOL = { 'Röd': '#d64545', 'Gul': '#e0b000', 'Blå': '#3a74c9', 'Vit': '#9aa3ad' };
  const zones = D.zones.map(z => ({ ...z, c: z.c || (z.p >= 15 ? 'Röd' : z.p >= 12 ? 'Gul' : z.p >= 6 ? 'Blå' : 'Vit') }));
  const zoneHours = z => z.all ? 'alla dagar 00–24' : `vardagar ${z.wk[0]}–${z.wk[1]}, dag före sön-/helgdag ${z.pre[0]}–${z.pre[1]}`;
  function zoneNow(z, t) {
    const ty = R.dayType(Math.floor(t / R.DAY)), h = (t % R.DAY) / 60;
    const hrs = z.all ? [0, 24] : ty === 'wk' ? z.wk : ty === 'pre' ? z.pre : null;
    return !!hrs && h >= hrs[0] && h < hrs[1];
  }
  function zoneRule(z, t) {
    const paying = zoneNow(z, t);
    return {
      t: `${z.c} avgiftszon (${z.p} kr/h)`, c: paying ? 'info' : 'ok', chip: paying ? `Avgift nu` : 'Gratis nu',
      p: `Betaltid ${zoneHours(z)}${z.max ? `, max ${z.max} h` : ''}. Sön- och helgdagar gratis${z.all ? ' gäller inte här' : ''}. Områdeskod ${z.code || '–'}.`,
    };
  }

  // ---------- Regler för en gatusida vid tid t ----------
  function evaluateSide(s, isLeft, t) {
    const [, , hwc, odd, flags, , , , zi] = s;
    const hw = HW[hwc];
    const rules = [];
    let status = 'ok';
    const rank = { ok: 0, soon: 1, unk: 2, no: 3 };
    const worst = st => { if (rank[st] > rank[status]) status = st; };

    if (isLeft ? flags & 1 : flags & 2) {
      rules.push({ t: 'Ingen parkering här', c: 'no', chip: 'Förbjudet', p: 'Enligt kartdata (OpenStreetMap) finns ingen tillåten parkering på den här sidan.' });
      worst('no');
    }
    if (hw === 'living_street') {
      rules.push({ t: 'Gångfartsområde', c: 'no', chip: 'Förbjudet', p: 'Parkering bara på särskilt markerade platser.' });
      worst('no');
    }
    if (odd === 0) {
      rules.unshift({ t: 'Datumparkering', c: 'unk', chip: 'Okänd sida', p: 'Kartan vet inte vilken sida som har udda husnummer här. Titta på husnumren: udda datum → förbjudet vid udda nummer (kl 00–06, 1 nov–15 maj).' });
      worst('unk');
    } else {
      const oddSide = (odd === 1) === isLeft;
      const w = R.datumNext(oddSide, t);
      const x = R.fromMin(t), sideTxt = oddSide ? 'udda' : 'jämna';
      let r;
      if (w && w.active) {
        r = { c: 'no', chip: 'Förbjudet nu', p: `Det är ${parity(Math.floor(t / R.DAY))} datum (${x.d}:e), och kl 00–06 är det förbjudet att parkera på sidan med ${sideTxt} nummer.` };
        worst('no');
      } else if (w && w.startsIn <= 12 * 60) {
        r = { c: 'soon', chip: 'Flytta i natt', p: `OK just nu, men förbudet börjar kl 00.00 natten mot ${dayLabel(w.day)} (${parity(w.day)} datum). Står du kvar efter midnatt måste bilen stå på andra sidan.` };
        worst('soon');
      } else {
        const why = !R.inSeason(x.m, x.d) ? 'Datumparkering gäller bara 1 nov–15 maj.' : (x.h < 6 ? `Idag (${x.d}:e) gäller förbudet andra sidan.` : 'Förbudet gäller bara kl 00–06.');
        r = { c: 'ok', chip: 'OK nu', p: why };
      }
      if (w && !w.active) r.p += ` Nästa förbud här: natten mot ${dayLabel(w.day)} kl 00–06.`;
      rules.unshift({ t: 'Datumparkering (1 nov–15 maj, 00–06)', ...r });
    }
    if (zi >= 0) rules.push(zoneRule(zones[zi], t));
    if (hw === 'primary' || hw === 'secondary') rules.push({ t: 'Större väg', c: 'info', chip: 'Kolla skylt', p: 'Kan vara huvudled. Där är parkering förbjuden.' });
    rules.push({ t: '24-timmarsregeln', c: 'info', chip: 'Info', p: 'Vardagar max 24 h i sträck på samma plats. Lördag, sön- och helgdag räknas inte.' });
    rules.push({ t: 'Allmänt', c: 'info', chip: 'Info', p: 'Inte inom 10 m från korsning eller före övergångsställe. Skyltar på plats gäller före kartan.' });
    return { status, rules };
  }

  // ---------- Karta ----------
  const map = L.map('map', { zoomControl: false, minZoom: 11, maxZoom: 19, preferCanvas: true })
    .setView([60.6749, 17.1413], 15);
  if (!L.Browser.mobile) L.control.zoom({ position: 'bottomright' }).addTo(map);
  map.attributionControl.setPrefix('');
  const touch = L.Browser.touch;
  // Bara gatusidornas canvas får ta emot tryck. Övriga canvas-lager ligger i egna
  // panes utan pointer-events, annars hamnar de ovanpå och svalde klicken.
  const pane = (name, z) => { const el = map.createPane(name); el.style.zIndex = z; el.style.pointerEvents = 'none'; return name; };
  const rBase = L.canvas({ padding: 0.3, pane: pane('under', 390) });
  const rTop = L.canvas({ padding: 0.3, pane: pane('over', 450) });
  const rSide = L.canvas({ padding: 0.3, tolerance: touch ? 12 : 6, pane: pane('sides', 420) });
  map.getPane('sides').style.pointerEvents = 'auto';

  if (APP.tiles) {
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
  } else {
    map.attributionControl.addAttribution('Kartdata © OpenStreetMap-bidragsgivare (ODbL)');
    const st = { park: { fill: true, fillColor: '#d6ead0', fillOpacity: 1, weight: 0 }, water: { fill: true, fillColor: '#b9d4ec', fillOpacity: 1, weight: 0 },
                 river: { color: '#aecbe6', weight: 8, fill: false }, coast: { color: '#8fb3d6', weight: 2, fill: false } };
    for (const [kind, enc] of D.area) {
      const Ctor = kind === 'park' || kind === 'water' ? L.polygon : L.polyline;
      Ctor(decode(enc), { ...st[kind], renderer: rBase, interactive: false }).addTo(map);
    }
    for (const [hwc, enc] of D.base) {
      const big = /motorway|trunk/.test(HW[hwc]);
      L.polyline(decode(enc), { color: big ? '#c7b9a6' : '#fff', weight: big ? 5 : 2, renderer: rBase, interactive: false }).addTo(map);
    }
  }

  const COLORS = { ok: '#1f9d55', no: '#d64545', soon: '#e0a100', unk: '#8a8f98' };
  const sides = [];
  const streetsByName = new Map();
  for (const s of D.streets) {
    const ll = decode(s[7]), xy = ll.map(xyOf), name = D.names[s[1]];
    if (!APP.tiles) L.polyline(ll, { color: '#fff', weight: 4, renderer: rBase, interactive: false }).addTo(map);
    for (const isLeft of [true, false]) {
      const line = L.polyline(ll, { weight: 4, renderer: rSide, lineCap: 'butt' }).addTo(map);
      const side = { s, isLeft, xy, line, name };
      line.on('click', () => showSide(side));
      sides.push(side);
    }
    if (!streetsByName.has(name)) streetsByName.set(name, []);
    streetsByName.get(name).push(ll);
  }

  let sideOffsetM = 3;
  function relayout() {
    const z = map.getZoom();
    const w = z >= 18 ? 7 : z >= 17 ? 5 : z >= 16 ? 4 : z >= 14 ? 3 : 2;
    const mpp = 156543.03 * Math.cos(LAT0 * Math.PI / 180) / Math.pow(2, z);
    sideOffsetM = (w / 2 + (z >= 16 ? 2.5 : 1)) * mpp;
    for (const sd of sides) {
      sd.line.setLatLngs(offset(sd.xy, sd.isLeft ? sideOffsetM : -sideOffsetM).map(llOf));
      sd.line.setStyle({ weight: w });
    }
    if (highlight && highlight.side) drawHighlight(highlight.side);
    if (z >= 15) lotLayer.addTo(map); else lotLayer.remove();
  }

  // ---------- Parkeringsplatser och p-hus ----------
  const lotLayer = L.layerGroup();
  const facLayer = L.layerGroup().addTo(map);
  const pIcon = (bg, big) => L.divIcon({ className: '', html: `<div class="pmark${big ? ' g' : ''}" style="background:${bg}">P</div>`, iconSize: big ? [28, 28] : [22, 22], iconAnchor: big ? [14, 14] : [11, 11] });
  const lots = D.lots.map(l => {
    const [lat, lon, fee, cap, kind, zi, ni, maxstay, name] = l;
    const lot = { lat, lon, fee, cap, kind, zi, near: D.names[ni], maxstay, name, ll: [lat, lon] };
    lot.title = name || `Parkeringsplats vid ${lot.near}`;
    const bg = zi >= 0 || fee === 2 ? '#3a74c9' : fee === 1 ? '#1f9d55' : '#8a8f98';
    L.marker(lot.ll, { icon: pIcon(bg), keyboard: false }).on('click', () => showLot(lot)).addTo(lotLayer);
    return lot;
  });
  const facilities = D.facilities.map(f => {
    const fac = { ...f, ll: [f.lat, f.lon] };
    L.marker(fac.ll, { icon: pIcon('#1d4f91', true), keyboard: false, title: f.name }).on('click', () => showFacility(fac)).addTo(facLayer);
    return fac;
  });

  // ---------- Läge (nu / i natt / vald tid) ----------
  let mode = 'now';
  const whenInput = $('when');
  function evalTime() {
    const n = nowMin();
    if (mode === 'night') { const today = Math.floor(n / R.DAY), h = (n % R.DAY) / 60; return (h < 3 ? today : today + 1) * R.DAY + 180; }
    if (mode === 'custom') return fromInput(whenInput.value) ?? n;
    return n;
  }

  function recolor() {
    const t = evalTime();
    for (const sd of sides) sd.line.setStyle({ color: COLORS[evaluateSide(sd.s, sd.isLeft, t).status] });
    renderSummary(t);
    if (sheetCtx && sheetCtx.refresh) sheetCtx.refresh();
  }

  function renderSummary(t) {
    const day = Math.floor(t / R.DAY), x = R.fromMin(t), odd = x.d % 2 === 1;
    let txt = `<b>${timeLabel(t)}</b> · `;
    if (R.inSeason(x.m, x.d) && x.h < 6) {
      txt += `${odd ? 'Udda' : 'Jämnt'} datum: parkera på <b class="ok">${odd ? 'jämna' : 'udda'} sidan</b>.`;
    } else if (R.inSeason(x.m, x.d)) {
      const nd = R.fromDayNum(day + 1);
      txt += R.inSeason(nd.m, nd.d)
        ? `Inget förbud nu. I natt (${nd.d % 2 ? 'udda' : 'jämnt'}): <b class="ok">${nd.d % 2 ? 'jämna' : 'udda'} sidan</b>.`
        : 'Datumparkeringen slutar i natt.';
    } else {
      txt += 'Ingen datumparkering (gäller 1 nov–15 maj).';
    }
    $('summary').innerHTML = txt;
  }

  // ---------- Bottenpanel ----------
  const sheet = $('sheet');
  let sheetCtx = null;
  function openSheet(html, state = 'peek', ctx = null) {
    $('sheetBody').innerHTML = html;
    $('sheetBody').scrollTop = 0;
    sheet.className = state;
    document.body.classList.add('sheet-open');
    sheetCtx = ctx;
  }
  function closeSheet() {
    sheet.className = '';
    document.body.classList.remove('sheet-open', 'picking');
    if (sheetCtx && sheetCtx.onClose) sheetCtx.onClose();
    sheetCtx = null;
    clearHighlight();
  }
  $('sheetClose').onclick = closeSheet;
  // Dra i handtaget: upp = helskärm, ner = mindre/stäng
  let dragY = null;
  $('grab').addEventListener('pointerdown', e => { dragY = e.clientY; });
  window.addEventListener('pointerup', e => {
    if (dragY === null) return;
    const dy = e.clientY - dragY; dragY = null;
    if (Math.abs(dy) < 8) sheet.className = sheet.className === 'full' ? 'peek' : 'full';
    else if (dy < -40) sheet.className = 'full';
    else if (dy > 40) sheet.className === 'full' ? (sheet.className = 'peek') : closeSheet();
  });

  // Synlig kartyta (ovanför panelen på mobil, vänster om den på dator)
  function visibleCenterOffset() {
    const open = document.body.classList.contains('sheet-open');
    if (innerWidth >= 820) return [open ? -212 : 0, 0];
    const top = $('top').getBoundingClientRect().bottom;
    const bottom = open ? Math.min(innerHeight, sheet.getBoundingClientRect().top) : innerHeight;
    return [0, innerHeight / 2 - (top + bottom) / 2];
  }
  function placeCrosshair() {
    const [ox, oy] = visibleCenterOffset();
    const ch = $('crosshair');
    ch.style.left = `calc(50% + ${ox}px)`; ch.style.top = `calc(50% - ${oy}px)`;
  }
  sheet.addEventListener('transitionend', placeCrosshair);
  window.addEventListener('resize', placeCrosshair);
  function focusOn(ll, zoom) {
    const z = zoom ?? Math.max(map.getZoom(), 17);
    const [ox, oy] = visibleCenterOffset();
    const p = map.project(ll, z).add([-ox, oy]);
    map.flyTo(map.unproject(p, z), z, { duration: 0.6 });
  }
  function mapCenterVisible() {
    const [ox, oy] = visibleCenterOffset();
    const c = map.getSize().divideBy(2).add([ox, -oy]);
    return map.containerPointToLatLng(c);
  }

  // ---------- Markering ----------
  let highlight = null;
  function drawHighlight(side) {
    if (highlight && highlight.layer) highlight.layer.remove();
    const layer = L.polyline(side.line.getLatLngs(), { color: '#1d232b', weight: side.line.options.weight + 7, opacity: .35, renderer: rBase, interactive: false, lineCap: 'butt' }).addTo(map);
    highlight = { side, layer };
  }
  function clearHighlight() { if (highlight && highlight.layer) highlight.layer.remove(); highlight = null; }

  const ruleHtml = rules => rules.map(r => `<div class="rule"><div class="hd"><span>${esc(r.t)}</span><span class="chip bg-${r.c}">${esc(r.chip)}</span></div><p>${esc(r.p)}</p></div>`).join('');
  const BIG = { ok: 'Du får parkera här', no: 'Du får INTE parkera här', soon: 'OK nu, men flytta före midnatt', unk: 'Osäkert: kolla husnumren' };

  function sideText(side) {
    const [, , , odd, flags, oddR, evenR] = side.s;
    if (odd === 0) return 'Okänd sida (udda/jämn)';
    const isOdd = (odd === 1) === side.isLeft, r = isOdd ? oddR : evenR;
    return `Sidan med ${isOdd ? 'udda' : 'jämna'} husnummer` + (r.length ? ` (nr ${r[0] === r[1] ? r[0] : r[0] + '–' + r[1]} här)` : '') + (flags & 4 ? ' · uppskattad från gatan intill' : '');
  }

  const backBtn = () => planState.active ? '<button class="pill" id="backPlan" style="margin-top:4px">← Till förslagen</button>' : '';
  function detailCtx(render) {
    const ctx = { refresh: () => { $('sheetBody').innerHTML = render(); wireBack(); } };
    if (planState.active) { ctx.onClose = exitPlan; document.body.classList.remove('picking'); }
    return ctx;
  }
  function wireBack() { const b = $('backPlan'); if (b) b.onclick = () => { sheetCtx = null; openPlanner(); }; }
  function showDetail(render) { openSheet(render(), 'peek', detailCtx(render)); wireBack(); }

  function showSide(side) {
    const render = () => {
      const t = evalTime();
      const { status, rules } = evaluateSide(side.s, side.isLeft, t);
      return `<div class="pop">${backBtn()}<h3>${esc(side.name)}</h3><div class="sub">${esc(sideText(side))} · ${timeLabel(t)}</div>
        <span class="big bg-${status}">${BIG[status]}${mode === 'now' ? ' nu' : ''}</span>${ruleHtml(rules)}</div>`;
    };
    showDetail(render);
    drawHighlight(side);
  }

  function showLot(lot) {
    const render = () => {
      const t = evalTime();
      const rules = [];
      if (lot.zi >= 0) rules.push(zoneRule(zones[lot.zi], t));
      else if (lot.fee === 1) rules.push({ t: 'Avgift', c: 'ok', chip: 'Gratis', p: 'Märkt som avgiftsfri i kartdata.' });
      else if (lot.fee === 2) rules.push({ t: 'Avgift', c: 'info', chip: 'Avgift', p: 'Avgiftsbelagd. Pris okänt, se skylten.' });
      else rules.push({ t: 'Avgift', c: 'unk', chip: 'Okänt', p: 'Okänt om avgift tas ut. Se skylten.' });
      rules.push({ t: 'Datumparkering', c: 'ok', chip: 'Gäller ej', p: 'Datumparkering gäller gatusidor, inte avgränsade parkeringsplatser. Vissa kommunala platser är vinterstängda 1 nov–15 maj där det är skyltat.' });
      rules.push({ t: '24-timmarsregeln', c: 'info', chip: 'Info', p: 'Vardagar max 24 h i sträck om inget annat är skyltat.' + (lot.maxstay ? ` Kartdata anger maxtid: ${lot.maxstay}.` : '') });
      return `<div class="pop">${backBtn()}<h3>${esc(lot.title)}</h3><div class="sub">${lot.kind === 'street_side' ? 'Parkeringsficka' : 'Parkeringsplats'}${lot.cap ? ` · ${lot.cap} platser` : ''} · ${timeLabel(t)}</div>${ruleHtml(rules)}<p class="muted">Ägare och regler kan variera. Skylten på plats gäller.</p></div>`;
    };
    clearHighlight();
    showDetail(render);
  }

  function facilityPrice(f) {
    const tr = f.tariff;
    if (!tr) return 'Pris: se Aimo-appen';
    if (tr.type === 'mobility') return `${tr.peak} kr/h vardagar ${tr.peakFrom}–${tr.peakTo}, annars ${tr.offpeak} kr/h`;
    return `${tr.first2} kr/h första 2 h, sedan ${tr.after} kr/h, max ${tr.cap24} kr/dygn`;
  }
  function showFacility(f) {
    const open = !f.open || (f.open[0] === 0 && f.open[1] === 24) ? 'Öppet dygnet runt' : `In/ut kl ${pad(f.open[0])}–${pad(f.open[1])}`;
    clearHighlight();
    showDetail(() => `<div class="pop">${backBtn()}<h3>${esc(f.name)}</h3><div class="sub">${esc(f.address)} · ${esc(f.operator)}</div>
      ${ruleHtml([
        { t: 'Pris', c: 'info', chip: 'Taxa', p: facilityPrice(f) },
        { t: 'Öppettider', c: 'info', chip: 'Info', p: open + (f.maxDays ? ` · max ${f.maxDays} dagar` : '') },
        { t: 'Datumparkering', c: 'ok', chip: 'Gäller ej', p: 'Parkeringshus omfattas inte av datumparkering eller 24-timmarsregeln.' },
      ])}<p class="muted">${esc(f.notes || '')}</p></div>`);
  }

  // ---------- Planerare ----------
  const planState = { active: false, from: null, to: null, preset: 'weekend', sort: 'best', results: null, target: null, sel: -1 };
  const resultLayer = L.layerGroup().addTo(map);

  function presetRange(p) {
    const n = nowMin(), today = Math.floor(n / R.DAY), wd = R.fromDayNum(today).wd;
    if (p === 'tonight') return [n, (today + 1) * R.DAY + 8 * 60];
    if (p === 'day') return [n, n + R.DAY];
    // I helgen: fredag 16 → söndag 20 (eller från nu om helgen redan börjat)
    const toFri = (5 - wd + 7) % 7;
    let from = (today + toFri) * R.DAY + 16 * 60;
    if (wd === 6 || wd === 0 || (wd === 5 && n > from)) from = n;
    const toSun = (7 - wd) % 7;
    let to = (today + toSun) * R.DAY + 20 * 60;
    if (to <= from) to = from + 2 * R.DAY;
    return [from, to];
  }

  function exitPlan() {
    planState.active = false;
    planState.results = null;
    planState.sel = -1;
    resultLayer.clearLayers();
    document.body.classList.remove('picking');
  }

  function openPlanner() {
    planState.active = true;
    clearHighlight();
    if (planState.from === null) [planState.from, planState.to] = presetRange(planState.preset);
    renderPlanner();
  }

  function renderPlanner() {
    const p = planState;
    if (p.results && p.sel >= 0) return renderSelected();
    document.body.classList.toggle('picking', !p.results);
    if (p.results) {
      const html = `<div class="pop"><h3>Förslag</h3><div id="pRes"></div>
        <button class="btn ghost" id="pAgain" style="margin-top:8px">Ändra plats eller tid</button></div>`;
      if (!sheetCtx || sheetCtx.kind !== 'plan') openSheet(html, 'full', { kind: 'plan', onClose: exitPlan });
      else $('sheetBody').innerHTML = html;
      $('pAgain').onclick = () => { p.results = null; resultLayer.clearLayers(); clearHighlight(); renderPlanner(); sheet.className = 'peek'; };
      renderResults();
      return;
    }
    const html = `<div class="pop"><h3>Planera parkering</h3>
      <div class="sub">Var kan bilen stå hela perioden? Lägg korset på kartan där du vill vara, till exempel vid stationen.</div>
      <div class="pills" id="presets">
        ${[['tonight', 'I natt'], ['weekend', 'I helgen'], ['day', 'Ett dygn']].map(([k, l]) => `<button class="pill${p.preset === k ? ' on' : ''}" data-p="${k}">${l}</button>`).join('')}
      </div>
      <div class="form">
        <div class="two dates">
          <label>Från<input type="datetime-local" id="pFrom" value="${toInput(p.from)}"></label>
          <label>Till<input type="datetime-local" id="pTo" value="${toInput(p.to)}"></label>
        </div>
        <div class="two">
          ${APP.tiles ? '<button class="btn ghost" id="pMe">◎ Min position</button>' : ''}
          <button class="btn" id="pGo" style="${APP.tiles ? '' : 'grid-column:1/3'}">Hitta parkering</button>
        </div>
      </div>
      <p class="muted">Förslagen räknas ut runt korset på kartan. Dra kartan så att korset hamnar där du ska vara.</p></div>`;
    if (!document.body.classList.contains('sheet-open') || !sheetCtx || sheetCtx.kind !== 'plan') {
      openSheet(html, 'peek', { kind: 'plan', onClose: exitPlan });
    } else $('sheetBody').innerHTML = html;
    setTimeout(placeCrosshair, 280);
    $('presets').onclick = e => {
      const k = e.target.dataset && e.target.dataset.p; if (!k) return;
      p.preset = k; [p.from, p.to] = presetRange(k); renderPlanner();
    };
    $('pFrom').onchange = e => { p.from = fromInput(e.target.value) ?? p.from; p.preset = null; };
    $('pTo').onchange = e => { p.to = fromInput(e.target.value) ?? p.to; p.preset = null; };
    if ($('pMe')) $('pMe').onclick = () => locate(true);
    $('pGo').onclick = () => { p.target = mapCenterVisible(); runPlan(); };
  }

  function runPlan() {
    const p = planState;
    if (!(p.to > p.from)) { toast('"Till" måste vara efter "Från".'); return; }
    p.results = findParking(p.from, p.to, [p.target.lat, p.target.lng]);
    p.sel = -1;
    renderPlanner();
    sheet.className = 'full';
  }

  function findParking(a, b, target) {
    const T = xyOf(target);
    const out = [];
    const counted = R.counted24(a, b);
    const over24 = counted > 24 * 60;
    let streetBlocked = 0;

    // Gatusidor
    const best = new Map();
    for (const sd of sides) {
      const [, , hwc, odd, flags, , , , zi] = sd.s;
      const hw = HW[hwc];
      if (odd === 0 || hw === 'living_street' || hw === 'primary' || hw === 'secondary') continue;
      if (sd.isLeft ? flags & 1 : flags & 2) continue;
      const near = nearestOn(T, sd.xy);
      if (near.d > 1200) continue;
      const oddSide = (odd === 1) === sd.isLeft;
      const key = sd.name + '|' + oddSide;
      if (R.datumConflicts(oddSide, a, b).length) { streetBlocked++; continue; }
      if (over24) { streetBlocked++; continue; }
      let cost = 0, notes = [];
      if (zi >= 0) {
        const f = R.zoneFee(zones[zi], a, b);
        if (f.maxExceeded) continue;
        cost = f.cost;
        notes.push(`${zones[zi].c} zon ${zones[zi].p} kr/h, ${Math.round(f.paidMin / 60)} h betaltid`);
      } else notes.push('Ingen avgiftszon');
      const prev = best.get(key);
      if (prev && prev.dist <= near.d) continue;
      best.set(key, {
        kind: 'street', title: sd.name, sub: `Gatuparkering, ${oddSide ? 'udda' : 'jämna'} sidan`, dist: near.d, cost, side: sd, ll: llOf(near.pt),
        notes: [...notes, R.datumConflicts(!oddSide, a, b).length ? 'Rätt sida för datumparkeringen hela perioden' : 'Ingen datumparkering under perioden'],
      });
    }
    out.push(...best.values());

    // Parkeringsplatser
    for (const lot of lots) {
      const d = distM(target, lot.ll);
      if (d > 2000) continue;
      if (over24) continue;
      let cost = 0, uncertain = false, notes = [];
      if (lot.zi >= 0) {
        const f = R.zoneFee(zones[lot.zi], a, b);
        if (f.maxExceeded) continue;
        cost = f.cost; notes.push(`${zones[lot.zi].c} zon ${zones[lot.zi].p} kr/h`);
      } else if (lot.fee === 2) { cost = null; notes.push('Avgift, pris okänt'); }
      else if (lot.fee === 0) { uncertain = true; notes.push('Avgift okänd, kolla skylt'); }
      else notes.push('Avgiftsfri enligt kartdata');
      out.push({ kind: 'lot', title: lot.title, sub: `Parkeringsplats${lot.cap ? `, ${lot.cap} platser` : ''}`, dist: d, cost, uncertain, ll: lot.ll, lot, notes });
    }

    // Parkeringshus
    for (const f of facilities) {
      const d = distM(target, f.ll);
      if (d > 6000) continue;
      if (f.maxDays && b - a > f.maxDays * R.DAY) continue;
      const cost = R.facilityCost(f.tariff, a, b);
      const warn = R.openOk(f.open, a, b) ? null : `Öppet bara ${pad(f.open[0])}–${pad(f.open[1])}: kontrollera att du kan köra in/ut`;
      out.push({ kind: 'garage', title: f.name, sub: `Parkeringshus, ${f.address}`, dist: d, cost, ll: f.ll, fac: f, warn, notes: [facilityPrice(f)] });
    }

    for (const r of out) {
      r.walk = walkMin(r.dist);
      r.score = r.walk + (r.cost == null ? 30 : r.cost / 6) + (r.uncertain ? 8 : 0) + (r.warn ? 45 : 0) + (r.kind === 'lot' && !r.lot.name ? 3 : 0);
    }
    const x = R.fromMin(a);
    const multiNight = R.datumConflicts(true, a, b).length && R.datumConflicts(false, a, b).length;
    return { list: out, streetBlocked, multiNight, over24, counted, season: R.inSeason(x.m, x.d) };
  }

  const resultCard = (r, i, sel) => `<div class="res${sel ? ' sel' : ''}" data-i="${i}">
      <div class="num">${i + 1}</div>
      <div><div class="t">${esc(r.title)}</div></div>
      <div class="price">${priceLabel(r)}</div>
      <div class="m">${esc(r.sub)} · ${walkLabel(r.dist)} (${r.walk} min promenad)</div>
      <div class="m">${esc(r.notes.join(' · '))}</div>
      ${r.warn ? `<div class="warn">⚠ ${esc(r.warn)}</div>` : ''}
    </div>`;

  function renderSelected() {
    const p = planState, list = sortedResults(), r = list[p.sel];
    document.body.classList.remove('picking');
    const html = `<div class="pop"><button class="pill" id="pAll" style="margin-top:4px">← Alla förslag</button>
      ${resultCard(r, p.sel, true)}
      <div class="two">
        <button class="btn ghost" id="pPrev" ${p.sel === 0 ? 'disabled style="opacity:.4"' : ''}>‹ Föregående</button>
        <button class="btn ghost" id="pNext" ${p.sel >= list.length - 1 ? 'disabled style="opacity:.4"' : ''}>Nästa ›</button>
      </div>
      <p class="muted">${timeLabel(p.from)} → ${timeLabel(p.to)}. Kontrollera skyltarna på plats.</p></div>`;
    $('sheetBody').innerHTML = html;
    $('pAll').onclick = () => { p.sel = -1; clearHighlight(); renderPlanner(); sheet.className = 'full'; };
    $('pPrev').onclick = () => selectResult(p.sel - 1, true);
    $('pNext').onclick = () => selectResult(p.sel + 1, true);
  }

  const priceLabel = r => r.cost == null ? 'Pris okänt' : r.cost === 0 ? (r.uncertain ? 'Troligen gratis' : 'Gratis') : `ca ${r.cost} kr`;

  function sortedResults() {
    const L_ = planState.results.list.slice();
    const s = planState.sort;
    if (s === 'near') L_.sort((p, q) => p.dist - q.dist);
    else if (s === 'cheap') L_.sort((p, q) => (p.cost ?? 1e9) - (q.cost ?? 1e9) || (!!p.uncertain - !!q.uncertain) || p.dist - q.dist);
    else L_.sort((p, q) => p.score - q.score);
    return L_.slice(0, 10);
  }

  function renderResults() {
    const p = planState, res = p.results, list = sortedResults();
    const notes = [];
    if (res.multiNight) notes.push(`<div class="note"><b>Flera nätter under datumparkeringen.</b> Förbudet byter sida varje natt, så bilen kan inte stå kvar på gatan. Förslagen nedan är parkeringsplatser och parkeringshus.</div>`);
    else if (res.over24) notes.push(`<div class="note"><b>Mer än 24 h vardagstid.</b> Perioden räknas till ${durLabel(res.counted)} enligt 24-timmarsregeln, så gatan och allmänna platser fungerar inte. Välj ett parkeringshus.</div>`);
    if (!list.length) notes.push('<div class="note">Hittade inget inom gångavstånd. Flytta korset och sök igen.</div>');
    $('pRes').innerHTML = `
      <div class="note blue">${timeLabel(p.from)} → ${timeLabel(p.to)} (${durLabel(p.to - p.from)})</div>
      ${notes.join('')}
      <div class="tabs" id="pTabs">
        ${[['best', 'Lämpligast'], ['near', 'Närmast'], ['cheap', 'Billigast']].map(([k, l]) => `<button data-s="${k}" class="${p.sort === k ? 'on' : ''}">${l}</button>`).join('')}
      </div>
      ${list.map((r, i) => resultCard(r, i, false)).join('')}
      <p class="muted">Priserna är uppskattningar från publicerade taxor. Lämpligast väger ihop gångavstånd, pris och osäkerhet. Kontrollera alltid skyltarna.</p>`;
    $('pTabs').onclick = e => { const s = e.target.dataset && e.target.dataset.s; if (!s) return; p.sort = s; p.sel = -1; renderResults(); };
    $('pRes').querySelectorAll('.res').forEach(el => el.onclick = () => selectResult(+el.dataset.i, true));
    drawResultMarkers(list);
  }

  function drawResultMarkers(list) {
    resultLayer.clearLayers();
    L.marker(planState.target, { icon: L.divIcon({ className: '', html: '<div class="tmark"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }), interactive: false }).addTo(resultLayer);
    list.forEach((r, i) => {
      L.marker(r.ll, { icon: L.divIcon({ className: '', html: `<div class="rmark${planState.sel === i ? ' sel' : ''}">${i + 1}</div>`, iconSize: [30, 30], iconAnchor: [15, 15] }), zIndexOffset: planState.sel === i ? 1000 : 0 })
        .on('click', () => selectResult(i, false)).addTo(resultLayer);
    });
  }

  function selectResult(i, fly) {
    const list = sortedResults();
    if (i < 0 || i >= list.length) return;
    planState.sel = i;
    const r = list[i];
    if (!sheetCtx || sheetCtx.kind !== 'plan') openSheet('', 'peek', { kind: 'plan', onClose: exitPlan });
    renderSelected();
    drawResultMarkers(list);
    sheet.className = 'peek';
    if (r.side) drawHighlight(r.side); else clearHighlight();
    setTimeout(() => focusOn(r.ll, fly ? 17 : map.getZoom()), 280);
  }

  // ---------- Gatunamn (bara utan bakgrundskarta) ----------
  if (!APP.tiles) {
    const Labels = L.Layer.extend({
      onAdd(m) { this._c = L.DomUtil.create('canvas'); this._c.style.pointerEvents = 'none'; m.getPanes().overlayPane.appendChild(this._c); m.on('moveend zoomend resize', this._draw, this); this._draw(); },
      onRemove(m) { this._c.remove(); m.off('moveend zoomend resize', this._draw, this); },
      _draw() {
        const m = this._map, z = m.getZoom(), size = m.getSize(), dpr = window.devicePixelRatio || 1, c = this._c;
        c.width = size.x * dpr; c.height = size.y * dpr; c.style.width = size.x + 'px'; c.style.height = size.y + 'px';
        L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0, 0]));
        const ctx = c.getContext('2d'); ctx.scale(dpr, dpr);
        if (z < 15) return;
        ctx.font = `${z >= 17 ? 13 : 12}px -apple-system, Segoe UI, Roboto, sans-serif`;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineWidth = 3.5; ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.fillStyle = '#333';
        const placed = [], b = m.getBounds().pad(0.05);
        for (const [name, parts] of streetsByName) {
          let best = null;
          for (const ll of parts) for (let i = 0; i < ll.length - 1; i++) {
            if (!b.contains(ll[i]) || !b.contains(ll[i + 1])) continue;
            const a = m.latLngToContainerPoint(ll[i]), q = m.latLngToContainerPoint(ll[i + 1]), len = a.distanceTo(q);
            if (!best || len > best.len) best = { a, q, len };
          }
          const tw = ctx.measureText(name).width;
          if (!best || best.len < tw + 10) continue;
          const cx = (best.a.x + best.q.x) / 2, cy = (best.a.y + best.q.y) / 2;
          if (placed.some(p => Math.abs(p[0] - cx) < (tw + p[2]) / 2 && Math.abs(p[1] - cy) < 18)) continue;
          placed.push([cx, cy, tw]);
          let ang = Math.atan2(best.q.y - best.a.y, best.q.x - best.a.x);
          if (ang > Math.PI / 2) ang -= Math.PI; else if (ang < -Math.PI / 2) ang += Math.PI;
          ctx.save(); ctx.translate(cx, cy); ctx.rotate(ang); ctx.strokeText(name, 0, 0); ctx.fillText(name, 0, 0); ctx.restore();
        }
      },
    });
    new Labels().addTo(map);
  }

  // ---------- Position ----------
  let meMarker = null, toastTimer = null;
  function toast(msg) {
    const el = $('toast'); el.textContent = msg; el.style.display = 'block';
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.style.display = 'none'; }, 4000);
  }
  const inGavle = ([la, lo]) => la > 60.58 && la < 60.76 && lo > 16.95 && lo < 17.35;
  function locate(userAsked) {
    if (!navigator.geolocation) { if (userAsked) toast('Webbläsaren kan inte visa position.'); return; }
    navigator.geolocation.getCurrentPosition(pos => {
      const ll = [pos.coords.latitude, pos.coords.longitude];
      if (meMarker) meMarker.setLatLng(ll);
      else meMarker = L.circleMarker(ll, { radius: 8, color: '#fff', weight: 3, fillColor: '#2a7de1', fillOpacity: 1, interactive: false, renderer: rTop }).addTo(map);
      if (inGavle(ll)) focusOn(ll, 17);
      else toast('Du verkar inte vara i Gävle. Kartan täcker bara Gävle än så länge.');
    }, err => {
      if (userAsked) toast(err.code === 1 ? 'Du har nekat positionen. Tillåt den i webbläsarens inställningar.' : 'Kunde inte hämta position.');
    }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 });
  }

  // ---------- UI ----------
  document.querySelectorAll('#mode button').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('#mode button').forEach(b => b.classList.toggle('on', b === btn));
    mode = btn.dataset.m;
    whenInput.hidden = mode !== 'custom';
    if (mode === 'custom' && !whenInput.value) whenInput.value = toInput(nowMin());
    recolor();
  }));
  whenInput.addEventListener('input', recolor);

  const names = [...streetsByName.keys()].sort((a, b) => a.localeCompare(b, 'sv'));
  $('streets').innerHTML = names.map(n => `<option value="${esc(n)}">`).join('');
  const search = $('search');
  function goStreet() {
    const q = search.value.trim().toLowerCase(); if (!q) return;
    const name = names.find(n => n.toLowerCase() === q) || names.find(n => n.toLowerCase().startsWith(q)) || names.find(n => n.toLowerCase().includes(q));
    if (!name) { toast(`Hittade ingen gata som heter "${search.value}".`); return; }
    search.value = name;
    map.fitBounds(L.latLngBounds(streetsByName.get(name).flat()), { maxZoom: 18, paddingTopLeft: [20, 170], paddingBottomRight: [20, 80] });
    search.blur();
  }
  search.addEventListener('change', goStreet);
  search.addEventListener('keydown', e => { if (e.key === 'Enter') goStreet(); });

  const help = $('help');
  $('helpBtn').onclick = () => help.classList.add('open');
  $('helpClose').onclick = () => help.classList.remove('open');
  help.addEventListener('click', e => { if (e.target === help) help.classList.remove('open'); });
  $('planBtn').onclick = openPlanner;
  if (APP.tiles) { $('locate').hidden = false; $('locate').onclick = () => locate(true); }

  map.on('zoomend', relayout);
  relayout();
  recolor();
  setInterval(() => { if (mode !== 'custom') recolor(); }, 60000);
  if (APP.tiles) locate(false);

  window.__dp = { map, sides, findParking, R, planState };
})();
