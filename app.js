const STORAGE_KEY = 'roll-call-data';
// Earlier versions seeded these demo athletes into localStorage.
const SAMPLE_KID_NAMES = {maya: 'Maya Alabrada', leo: 'Leo Alabrada'};
// When the same match comes from several sources, the first source listed supplies event and division names.
const SOURCE_PRIORITY = ['smoothcomp', 'jits.gg'];
const STABLE_ID = /-\d{4}-\d{2}-\d{2}-/;

const $ = id => document.getElementById(id);

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[char]);

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch {
    return '';
  }
}

function formatDate(value, options = {month: 'short', day: 'numeric', year: 'numeric'}) {
  const date = new Date(String(value).length === 10 ? `${value}T12:00:00` : value);
  return Number.isNaN(date.getTime()) ? String(value ?? '') : date.toLocaleDateString('en-US', options);
}

const normalizeName = name => String(name ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();

const sourceRank = source => {
  const index = SOURCE_PRIORITY.indexOf(source);
  return index < 0 ? SOURCE_PRIORITY.length : index;
};

function loadData() {
  let stored = null;
  try {
    stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
  } catch {
    stored = null;
  }
  const saved = stored && Array.isArray(stored.kids) && Array.isArray(stored.matches) ? stored : {kids: [], matches: []};
  const sampleIds = new Set(saved.kids.filter(kid => SAMPLE_KID_NAMES[kid.id] === kid.name).map(kid => kid.id));
  return {...saved, kids: saved.kids.filter(kid => !sampleIds.has(kid.id)), matches: saved.matches.filter(match => !sampleIds.has(match.kidId))};
}

function saveData() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    showToast('Could not save to this browser. Changes will be lost on reload.');
  }
}

let data = loadData();
let selectedKid = data.kids[0]?.id || '';
let opponentFilter = 'all';

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 3000);
}

// Pairs the same match reported by different sources (same day, opponent, result and Gi/No-Gi).
function combinedMatches(kidId) {
  const kidMatches = data.matches.filter(match => match.kidId === kidId).sort((a, b) => sourceRank(a.source) - sourceRank(b.source));
  const eventByDate = {};
  kidMatches.forEach(match => {
    if (match.event && !eventByDate[match.date]) eventByDate[match.date] = match.event;
  });
  const waiting = {};
  const combined = [];
  kidMatches.forEach(match => {
    const key = [match.date, normalizeName(match.opponent), match.result, match.format || ''].join('|');
    const partner = (waiting[key] || []).find(entry => !entry.sources.includes(match.source));
    if (partner) {
      partner.sources.push(match.source);
      ['division', 'weight', 'method', 'format'].forEach(field => {
        if (!partner[field] && match[field]) partner[field] = match[field];
      });
      return;
    }
    const entry = {...match, event: eventByDate[match.date] || match.event, sources: [match.source || 'manual']};
    (waiting[key] ||= []).push(entry);
    combined.push(entry);
  });
  return combined.sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

const matches = () => combinedMatches(selectedKid);

function searchedMatches() {
  const query = $('search-input').value.trim().toLowerCase();
  return matches().filter(match => [match.opponent, match.event, match.division, match.weight, match.format, match.method, ...match.sources].join(' ').toLowerCase().includes(query));
}

const competitionKey = match => `${match.date}|${match.event}`;

const resultPill = result => `<span class="result-pill ${result === 'win' ? 'win' : 'loss'}">${result === 'win' ? 'W' : 'L'}</span>`;

function opponentGroups(rows) {
  const groups = {};
  rows.forEach(match => {
    const key = normalizeName(match.opponent);
    if (!groups[key]) groups[key] = {name: match.opponent, matches: [], competitions: new Set(), wins: 0, losses: 0};
    const group = groups[key];
    group.matches.push(match);
    group.competitions.add(competitionKey(match));
    group[match.result === 'win' ? 'wins' : 'losses'] += 1;
  });
  return Object.values(groups)
    .map(group => ({...group, matches: group.matches.sort((a, b) => String(a.date).localeCompare(String(b.date)))}))
    .sort((a, b) => b.competitions.size - a.competitions.size || b.matches.length - a.matches.length || a.name.localeCompare(b.name));
}

function renderOpponents(target, limit, filter = 'all') {
  const allGroups = opponentGroups(searchedMatches());
  if (target === $('all-opponents')) $('rematch-count').textContent = allGroups.filter(group => group.competitions.size > 1).length;
  const groups = allGroups.filter(group => filter !== 'rematch' || group.competitions.size > 1).slice(0, limit || Infinity);
  const empty = filter === 'rematch' ? 'No opponent has been met at more than one competition yet.' : 'No opponents match this search.';
  target.innerHTML = groups.length ? groups.map(group => `
    <article class="opponent-card${group.competitions.size > 1 ? ' rematch' : ''}">
      <div class="opponent-top"><span class="opponent-name">${escapeHtml(group.name)}</span><span class="opponent-count">${group.matches.length} ${group.matches.length === 1 ? 'match' : 'matches'}</span></div>
      <div class="opponent-record"><strong><span class="record-win">${group.wins}W</span> – <span class="record-loss">${group.losses}L</span></strong><small>head to head</small></div>
      ${group.competitions.size > 1 ? `<span class="rematch-badge">Met at ${group.competitions.size} competitions</span>` : ''}
      <ul class="opponent-matches">${group.matches.map(match => `
        <li>${resultPill(match.result)}<span><b>${escapeHtml(match.event || 'Unknown event')}</b><br>${escapeHtml([formatDate(match.date), match.format, match.method].filter(Boolean).join(' · '))}</span></li>`).join('')}
      </ul>
    </article>`).join('') : `<div class="empty">${empty}</div>`;
}

function renderMatches(target, limit) {
  const rows = searchedMatches().slice(0, limit || Infinity);
  target.innerHTML = rows.length ? rows.map(match => `
    <article class="match-row">
      <span class="match-date">${escapeHtml(formatDate(match.date))}</span>
      <span class="match-opponent">${escapeHtml(match.opponent)}</span>
      <span class="match-event">${escapeHtml(match.event)}<small>${escapeHtml([match.format, match.method].filter(Boolean).join(' · '))}</small></span>
      <span class="match-division">${escapeHtml(match.division)}</span>
      <span class="match-result">${resultPill(match.result)}<small>${escapeHtml(match.sources.join(' + '))}</small></span>
    </article>`).join('') : '<div class="empty">No matches match this search.</div>';
}

// ---- Reports ----------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs = {}, parent) {
  const element = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
  if (parent) parent.appendChild(element);
  return element;
}

function svgText(parent, x, y, text, attrs = {}) {
  const element = svgEl('text', {x, y, ...attrs}, parent);
  element.textContent = text;
  return element;
}

// Upper limit of a weight class in lbs: "Under 80lbs" -> 80, "66-75 lbs." -> 75, "-52 kg" -> 114.6. Open classes return null.
function weightLimitLbs(weight) {
  const text = String(weight || '').toLowerCase();
  const numbers = (text.match(/\d+(?:\.\d+)?/g) || []).map(Number);
  if (!numbers.length || /over|\+/.test(text)) return null;
  const limit = Math.max(...numbers);
  return /kg/.test(text) ? Math.round(limit * 2.20462 * 10) / 10 : limit;
}

const MEDAL_TYPES = [['gold', '🥇', 'Gold'], ['silver', '🥈', 'Silver'], ['bronze', '🥉', 'Bronze']];

// Medals per competition. Each source lists division results separately, so take the larger count per medal type rather than adding sources together.
function medalsByDate(placements) {
  const byDate = {};
  placements.forEach(placement => {
    const entry = byDate[placement.date] ||= {event: placement.event, counts: {}, bestPlace: null};
    const counts = entry.counts[placement.source] ||= {gold: 0, silver: 0, bronze: 0};
    if (placement.medal) counts[placement.medal] += 1;
    if (placement.place && (!entry.bestPlace || placement.place < entry.bestPlace)) entry.bestPlace = placement.place;
    if (placement.source === 'smoothcomp' && placement.event) entry.event = placement.event;
  });
  return Object.fromEntries(Object.entries(byDate).map(([date, entry]) => {
    const medals = Object.fromEntries(MEDAL_TYPES.map(([type]) => [type, Math.max(0, ...Object.values(entry.counts).map(counts => counts[type]))]));
    return [date, {event: entry.event, medals, bestPlace: entry.bestPlace}];
  }));
}

function competitionsFor(rows, placements = []) {
  const byKey = {};
  rows.forEach(match => {
    const key = competitionKey(match);
    const competition = byKey[key] ||= {date: match.date, event: match.event || 'Unknown event', wins: 0, losses: 0, limits: new Set()};
    competition[match.result === 'win' ? 'wins' : 'losses'] += 1;
    const limit = weightLimitLbs(match.weight);
    if (limit) competition.limits.add(limit);
  });
  const results = medalsByDate(placements);
  const competitions = Object.values(byKey);
  Object.entries(results).forEach(([date, result]) => {
    if (!competitions.some(competition => competition.date === date)) competitions.push({date, event: result.event || 'Unknown event', wins: 0, losses: 0, limits: new Set()});
  });
  const claimed = new Set();
  return competitions
    .sort((a, b) => String(a.date).localeCompare(String(b.date)))
    .map(competition => {
      // Several competitions on one day share that day's results; attach them to the first only.
      const result = claimed.has(competition.date) ? null : results[competition.date];
      claimed.add(competition.date);
      return {...competition, weightLimit: competition.limits.size ? Math.min(...competition.limits) : null, medals: result?.medals || null, bestPlace: result?.bestPlace || null};
    });
}

function medalText(competition) {
  if (!competition.medals) return '—';
  const earned = MEDAL_TYPES.filter(([type]) => competition.medals[type]).map(([type, icon, label]) => `${icon} ${competition.medals[type]} ${label}`);
  if (earned.length) return earned.join('  ');
  return competition.bestPlace ? `${competition.bestPlace}${['th', 'st', 'nd', 'rd'][competition.bestPlace % 10 > 3 || [11, 12, 13].includes(competition.bestPlace % 100) ? 0 : competition.bestPlace % 10]} place` : 'No medal';
}

function renderCompetitionList(competitions) {
  const table = $('competition-table');
  table.replaceChildren();
  if (!competitions.length) {
    $('competition-empty').hidden = false;
    return;
  }
  $('competition-empty').hidden = true;
  const head = table.createTHead().insertRow();
  [['Competition'], ['Date'], ['Wins', 'num'], ['Losses', 'num'], ['Medals']].forEach(([label, className]) => {
    const cell = document.createElement('th');
    cell.textContent = label;
    if (className) cell.className = className;
    head.appendChild(cell);
  });
  const body = table.createTBody();
  [...competitions].reverse().forEach(competition => {
    const row = body.insertRow();
    row.insertCell().textContent = competition.event;
    row.insertCell().textContent = formatDate(competition.date);
    [['wins', 'win'], ['losses', 'loss']].forEach(([key, result]) => {
      const cell = row.insertCell();
      cell.className = 'num';
      const pill = document.createElement('span');
      pill.className = `count-pill ${result}`;
      pill.textContent = competition[key];
      cell.appendChild(pill);
    });
    const medals = row.insertCell();
    medals.className = 'medals';
    medals.textContent = medalText(competition);
  });
  const totals = table.createTFoot().insertRow();
  const sum = key => competitions.reduce((total, competition) => total + competition[key], 0);
  const medalTotals = Object.fromEntries(MEDAL_TYPES.map(([type]) => [type, competitions.reduce((total, competition) => total + (competition.medals?.[type] || 0), 0)]));
  [`${competitions.length} competitions`, '', sum('wins'), sum('losses'), medalText({medals: medalTotals}).replace('No medal', '—')].forEach((value, index) => {
    const cell = totals.insertCell();
    cell.textContent = value;
    if (index === 2 || index === 3) cell.className = 'num';
  });
}

function niceStep(range, targetTicks) {
  const raw = range / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map(multiple => multiple * magnitude).find(step => step >= raw);
}

function truncate(text, maxChars) {
  return text.length > maxChars ? `${text.slice(0, Math.max(1, maxChars - 1)).trim()}…` : text;
}

function showTooltip(event, title, rows) {
  const tooltip = $('chart-tooltip');
  tooltip.replaceChildren();
  const heading = document.createElement('div');
  heading.className = 'tip-title';
  heading.textContent = title;
  tooltip.appendChild(heading);
  rows.forEach(([value, label, color]) => {
    const row = document.createElement('div');
    row.className = 'tip-row';
    if (color) {
      const key = document.createElement('i');
      key.className = 'tip-key';
      key.style.background = color;
      row.appendChild(key);
    }
    const strong = document.createElement('strong');
    strong.textContent = value;
    row.append(strong, document.createTextNode(` ${label}`));
    tooltip.appendChild(row);
  });
  tooltip.hidden = false;
  const box = event.target.getBoundingClientRect?.();
  const x = event.clientX ?? (box.left + box.width / 2);
  const y = event.clientY ?? box.top;
  const width = tooltip.offsetWidth;
  tooltip.style.left = `${Math.min(Math.max(8, x + 14), window.innerWidth - width - 8)}px`;
  tooltip.style.top = `${Math.max(8, y - tooltip.offsetHeight - 12)}px`;
}

const hideTooltip = () => { $('chart-tooltip').hidden = true; };

function fillTable(table, headers, rows) {
  table.replaceChildren();
  const head = table.createTHead().insertRow();
  headers.forEach(header => {
    const cell = document.createElement('th');
    cell.textContent = header;
    head.appendChild(cell);
  });
  const body = table.createTBody();
  rows.forEach(values => {
    const row = body.insertRow();
    values.forEach(value => { row.insertCell().textContent = value; });
  });
}

function renderWeightChart(container, competitions) {
  const points = competitions.filter(competition => competition.weightLimit);
  container.replaceChildren();
  fillTable($('weight-table'), ['Date', 'Competition', 'Weight class limit (lbs)'], competitions.map(c => [formatDate(c.date), c.event, c.weightLimit ?? '—']));
  if (!points.length) {
    container.innerHTML = '<div class="chart-empty">No weight classes found in the division names yet.</div>';
    return;
  }
  const width = Math.max(320, container.clientWidth || 700);
  const height = 260;
  const margin = {top: 24, right: 56, bottom: 36, left: 44};
  const times = points.map(point => new Date(`${point.date}T12:00:00`).getTime());
  const [minTime, maxTime] = [Math.min(...times), Math.max(...times)];
  const values = points.map(point => point.weightLimit);
  const step = niceStep(Math.max(10, Math.max(...values) - Math.min(...values)), 4);
  const yMin = Math.floor((Math.min(...values) - step / 2) / step) * step;
  const yMax = Math.ceil((Math.max(...values) + step / 2) / step) * step;
  const x = time => maxTime === minTime ? (margin.left + width - margin.right) / 2 : margin.left + (time - minTime) / (maxTime - minTime) * (width - margin.left - margin.right);
  const y = value => margin.top + (yMax - value) / (yMax - yMin) * (height - margin.top - margin.bottom);
  const svg = svgEl('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Weight class limit per competition over time'}, container);

  for (let value = yMin; value <= yMax; value += step) {
    svgEl('line', {class: 'grid', x1: margin.left, x2: width - margin.right, y1: y(value), y2: y(value)}, svg);
    svgText(svg, margin.left - 8, y(value) + 4, value, {'text-anchor': 'end'});
  }
  const tickCount = Math.min(points.length, Math.max(2, Math.floor((width - margin.left - margin.right) / 110)));
  const tickIndexes = [...new Set(Array.from({length: tickCount}, (_, i) => Math.round(i * (points.length - 1) / Math.max(1, tickCount - 1))))];
  tickIndexes.forEach(index => svgText(svg, x(times[index]), height - 12, formatDate(points[index].date, {month: 'short', year: 'numeric'}), {'text-anchor': 'middle'}));

  const path = points.map((point, index) => `${index ? 'L' : 'M'}${x(times[index])},${y(point.weightLimit)}`).join(' ');
  svgEl('path', {d: path, fill: 'none', stroke: 'var(--ink)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}, svg);
  points.forEach((point, index) => svgEl('circle', {cx: x(times[index]), cy: y(point.weightLimit), r: 4.5, fill: 'var(--ink)', stroke: '#fff', 'stroke-width': 2}, svg));
  const last = points.length - 1;
  svgText(svg, x(times[last]) + 10, y(points[last].weightLimit) + 4, `${points[last].weightLimit} lbs`, {class: 'value-label'});

  // Crosshair snaps to the nearest competition.
  const crosshair = svgEl('line', {class: 'baseline', y1: margin.top, y2: height - margin.bottom, visibility: 'hidden'}, svg);
  const hit = svgEl('rect', {class: 'hit', x: margin.left - 10, y: 0, width: width - margin.left - margin.right + 20, height, tabindex: 0, 'aria-label': 'Weight chart, use arrow keys to step through competitions'}, svg);
  let focused = last;
  const highlight = (index, event) => {
    focused = index;
    const cx = x(times[index]);
    crosshair.setAttribute('x1', cx);
    crosshair.setAttribute('x2', cx);
    crosshair.setAttribute('visibility', 'visible');
    const point = points[index];
    const classes = [...point.limits].sort((a, b) => a - b).join(', ');
    showTooltip(event, `${formatDate(point.date)} · ${point.event}`, [[`${point.weightLimit} lbs`, 'lightest class', 'var(--ink)'], ...(point.limits.size > 1 ? [[classes, 'all classes (lbs)']] : [])]);
  };
  hit.addEventListener('pointermove', event => {
    const box = svg.getBoundingClientRect();
    const pointerX = (event.clientX - box.left) * (width / box.width);
    const nearest = times.reduce((best, time, index) => Math.abs(x(time) - pointerX) < Math.abs(x(times[best]) - pointerX) ? index : best, 0);
    highlight(nearest, event);
  });
  hit.addEventListener('focus', () => {
    const box = hit.getBoundingClientRect();
    highlight(focused, {clientX: box.left + (x(times[focused]) / width) * box.width, clientY: box.top + 20});
  });
  hit.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const next = Math.min(points.length - 1, Math.max(0, focused + (event.key === 'ArrowRight' ? 1 : -1)));
    const box = hit.getBoundingClientRect();
    highlight(next, {clientX: box.left + (x(times[next]) / width) * box.width, clientY: box.top + 20});
  });
  const clear = () => { crosshair.setAttribute('visibility', 'hidden'); hideTooltip(); };
  hit.addEventListener('pointerleave', clear);
  hit.addEventListener('blur', clear);
}

// Rounded (4px) at the data end, square at the baseline.
function barPath(x, baseline, width, length, up) {
  const radius = Math.min(4, length, width / 2);
  const end = up ? baseline - length : baseline + length;
  const sign = up ? 1 : -1;
  return `M${x},${baseline} V${end + sign * radius} Q${x},${end} ${x + radius},${end} H${x + width - radius} Q${x + width},${end} ${x + width},${end + sign * radius} V${baseline} Z`;
}

function renderResultsChart(container, competitions) {
  container.replaceChildren();
  fillTable($('results-table'), ['Date', 'Competition', 'Wins', 'Losses'], competitions.map(c => [formatDate(c.date), c.event, c.wins, c.losses]));
  if (!competitions.length) {
    container.innerHTML = '<div class="chart-empty">No matches to chart yet.</div>';
    return;
  }
  const width = Math.max(320, container.clientWidth || 700);
  const margin = {top: 22, right: 12, bottom: 64, left: 36};  // bottom leaves room for the loss labels and two axis lines
  const maxCount = Math.max(1, ...competitions.map(c => Math.max(c.wins, c.losses)));
  const step = maxCount <= 5 ? 1 : niceStep(maxCount, 4);
  const top = Math.ceil(maxCount / step) * step;
  const halfHeight = 95;
  const height = margin.top + halfHeight * 2 + margin.bottom;
  const baseline = margin.top + halfHeight;
  const scale = value => value / top * halfHeight;
  const band = (width - margin.left - margin.right) / competitions.length;
  const barWidth = Math.min(24, band * 0.5);
  const svg = svgEl('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Wins and losses per competition'}, container);

  for (let value = step; value <= top; value += step) {
    [baseline - scale(value), baseline + scale(value)].forEach(position => svgEl('line', {class: 'grid', x1: margin.left, x2: width - margin.right, y1: position, y2: position}, svg));
    svgText(svg, margin.left - 8, baseline - scale(value) + 4, value, {'text-anchor': 'end'});
    svgText(svg, margin.left - 8, baseline + scale(value) + 4, value, {'text-anchor': 'end'});
  }
  svgEl('line', {class: 'baseline', x1: margin.left, x2: width - margin.right, y1: baseline, y2: baseline}, svg);

  const plot = svgEl('g', {}, svg);
  const maxChars = Math.floor((band - 14) / 6.8);
  competitions.forEach((competition, index) => {
    const center = margin.left + band * index + band / 2;
    const left = center - barWidth / 2;
    const group = svgEl('g', {}, plot);
    if (competition.wins) svgEl('path', {class: 'bar', d: barPath(left, baseline - 1, barWidth, scale(competition.wins) - 1, true), fill: 'var(--win)'}, group);
    if (competition.losses) svgEl('path', {class: 'bar', d: barPath(left, baseline + 1, barWidth, scale(competition.losses) - 1, false), fill: 'var(--loss)'}, group);
    svgText(group, center, baseline - scale(competition.wins) - 6, competition.wins, {class: 'value-label', 'text-anchor': 'middle'});
    svgText(group, center, baseline + scale(competition.losses) + 15, competition.losses, {class: 'value-label', 'text-anchor': 'middle'});
    svgText(svg, center, height - 24, formatDate(competition.date, band < 70 ? {month: 'short', year: '2-digit'} : {month: 'short', day: 'numeric', year: 'numeric'}), {'text-anchor': 'middle'});
    if (maxChars >= 6) svgText(svg, center, height - 8, truncate(competition.event, maxChars), {'text-anchor': 'middle'});

    const hit = svgEl('rect', {class: 'hit', x: center - band / 2, y: margin.top - 10, width: band, height: halfHeight * 2 + 20, tabindex: 0, 'aria-label': `${competition.event}, ${formatDate(competition.date)}: ${competition.wins} wins, ${competition.losses} losses`}, plot);
    const enter = event => {
      plot.classList.add('dimmed');
      group.querySelectorAll('.bar').forEach(bar => bar.classList.add('hover'));
      const record = competition.wins + competition.losses;
      showTooltip(event, `${formatDate(competition.date)} · ${competition.event}`, [[competition.wins, `win${competition.wins === 1 ? '' : 's'}`, 'var(--win)'], [competition.losses, `loss${competition.losses === 1 ? '' : 'es'}`, 'var(--loss)'], [`${Math.round(competition.wins / record * 100)}%`, 'win rate']]);
    };
    const leave = () => {
      plot.classList.remove('dimmed');
      group.querySelectorAll('.bar').forEach(bar => bar.classList.remove('hover'));
      hideTooltip();
    };
    hit.addEventListener('pointermove', enter);
    hit.addEventListener('focus', enter);
    hit.addEventListener('pointerleave', leave);
    hit.addEventListener('blur', leave);
  });
}

function renderReports(kidMatches) {
  const competitions = competitionsFor(kidMatches, (data.placements || []).filter(placement => placement.kidId === selectedKid));
  $('reports-count-label').textContent = `${competitions.length} competition${competitions.length === 1 ? '' : 's'}`;
  if (!$('reports-view').classList.contains('active-view')) return;  // charts need a visible container to measure
  renderCompetitionList(competitions);
  renderWeightChart($('weight-chart'), competitions);
  renderResultsChart($('results-chart'), competitions);
}

function renderSourceStats(kid, kidMatches) {
  const source = kid?.jitsStats || data.sources?.find(item => item.kidId === kid?.id && item.source === 'jits.gg');
  const stats = $('source-stats');
  stats.hidden = !source;
  if (!source) return;
  const jitsRows = kidMatches.filter(match => match.sources.includes('jits.gg')).length;
  const status = !jitsRows
    ? 'Profile statistics imported; no individual match rows were returned yet.'
    : source.matchesRecorded > jitsRows
      ? `${jitsRows} of ${source.matchesRecorded} match rows imported. Sign in to Jits.gg during sync to get the rest.`
      : 'Match rows imported.';
  const url = safeUrl(source.url);
  stats.innerHTML = `
    <div><div class="eyebrow">public source snapshot</div><h3>Jits.gg overview</h3><p class="source-status">${escapeHtml(status)}</p></div>
    <div class="source-stat-row">
      <span><strong>${escapeHtml(source.matchesRecorded ?? '—')}</strong> recorded matches</span>
      <span><strong>${escapeHtml(source.record?.wins ?? '—')}–${escapeHtml(source.record?.losses ?? '—')}</strong> record</span>
      <span><strong>${escapeHtml(source.tournaments ?? '—')}</strong> tournaments</span>
      ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">Open profile ↗</a>` : ''}
    </div>`;
}

function render() {
  const kid = data.kids.find(item => item.id === selectedKid);
  const kidMatches = kid ? matches() : [];
  const groups = opponentGroups(kidMatches);
  $('kid-name').textContent = kid ? kid.name : 'No athletes yet';
  $('match-count').textContent = kidMatches.length;
  $('stat-matches').textContent = kidMatches.length;
  $('stat-opponents').textContent = groups.length;
  $('stat-events').textContent = new Set(kidMatches.map(match => `${match.date}|${match.event}`)).size;
  $('stat-weight').textContent = kidMatches.find(match => match.weight)?.weight || '—';
  $('stat-division').textContent = kidMatches[0]?.division || (kid ? 'No division yet' : 'Add a kid or import a sync file');
  $('matches-count-label').textContent = `${kidMatches.length} logged`;
  $('opponents-count-label').textContent = `${groups.length} opponents`;
  renderSourceStats(kid, kidMatches);
  renderOpponents($('opponent-preview'), 3);
  renderMatches($('match-preview'), 4);
  renderMatches($('all-matches'));
  renderOpponents($('all-opponents'), 0, opponentFilter);
  renderReports(kidMatches);
  $('last-sync').textContent = data.updatedAt ? `Updated ${formatDate(data.updatedAt, {month: 'short', day: 'numeric'})}` : 'Not synced yet';
  saveData();
}

function switchView(view) {
  document.querySelectorAll('.view').forEach(element => element.classList.remove('active-view'));
  $(`${view}-view`).classList.add('active-view');
  document.querySelectorAll('.nav-item').forEach(element => element.classList.toggle('active', element.dataset.view === view));
  $('page-title').textContent = {overview: 'The family ledger', matches: 'Every match', opponents: 'Opponent index', reports: 'Progress report'}[view] || 'Sources & sync';
  hideTooltip();
  if (view === 'reports') render();
}

// Merges an import into the journal: kids update in place, matches from the same source replace older copies.
function mergeImport(imported) {
  const kids = [...data.kids];
  let matchesSoFar = [...data.matches];
  let placementsSoFar = [...(data.placements || [])];
  imported.kids.forEach(kid => {
    let index = kids.findIndex(existing => existing.id === kid.id);
    if (index < 0) {
      index = kids.findIndex(existing => normalizeName(existing.name) === normalizeName(kid.name));
      if (index >= 0) {
        const renamed = row => (row.kidId === kids[index].id ? {...row, kidId: kid.id} : row);
        matchesSoFar = matchesSoFar.map(renamed);
        placementsSoFar = placementsSoFar.map(renamed);
      }
    }
    if (index < 0) kids.push(kid);
    else kids[index] = {...kids[index], ...kid};
  });

  const importedPlacements = imported.placements || [];
  const syncedSources = new Set([...imported.matches, ...importedPlacements, ...(imported.sources || [])].map(item => `${item.kidId}|${item.source}`));
  // Keep earlier rows the import did not return (e.g. a logged-out sync sees fewer rows), except legacy positional ids.
  const keepEarlier = (earlier, incoming) => {
    const incomingIds = new Set(incoming.map(row => row.id));
    return [...earlier.filter(row => !incomingIds.has(row.id) && !(syncedSources.has(`${row.kidId}|${row.source}`) && !STABLE_ID.test(row.id || ''))), ...incoming];
  };
  const sources = [...(data.sources || []).filter(item => !syncedSources.has(`${item.kidId}|${item.source}`)), ...(imported.sources || [])];
  return {...data, ...imported, kids, matches: keepEarlier(matchesSoFar, imported.matches), placements: keepEarlier(placementsSoFar, importedPlacements), sources, updatedAt: imported.updatedAt || new Date().toISOString()};
}

function importData(file) {
  const reader = new FileReader();
  reader.onload = event => {
    let imported;
    try {
      imported = JSON.parse(event.target.result);
    } catch {
      showToast('That file is not valid JSON.');
      return;
    }
    if (!Array.isArray(imported.kids) || !Array.isArray(imported.matches)) {
      showToast('That file needs kids and matches arrays.');
      return;
    }
    const before = data.matches.length;
    data = mergeImport(imported);
    if (!data.kids.some(kid => kid.id === selectedKid)) selectedKid = data.kids[0]?.id || '';
    populateKids();
    render();
    showToast(`Journal imported: ${data.matches.length - before >= 0 ? '+' : ''}${data.matches.length - before} match records.`);
  };
  reader.readAsText(file);
  $('file-input').value = '';
}

function populateKids() {
  $('kid-select').innerHTML = data.kids.map(kid => `<option value="${escapeHtml(kid.id)}">${escapeHtml(kid.name)}</option>`).join('');
  $('kid-select').value = selectedKid;
}

function addKid(event) {
  event.preventDefault();
  const name = $('new-kid-name').value.trim();
  if (!name) return;
  const id = `kid-${Date.now()}`;
  data.kids.push({id, name, jitsUrl: safeUrl($('new-kid-jits').value.trim()), smoothcompUrl: safeUrl($('new-kid-smoothcomp').value.trim())});
  selectedKid = id;
  $('add-kid-panel').reset();
  $('add-kid-panel').hidden = true;
  populateKids();
  render();
  showToast(`${name} added to the ledger.`);
}

$('kid-select').addEventListener('change', event => {
  selectedKid = event.target.value;
  render();
});
$('search-input').addEventListener('input', render);
$('clear-search').addEventListener('click', () => {
  $('search-input').value = '';
  render();
});
$('add-kid-button').addEventListener('click', () => {
  $('add-kid-panel').hidden = !$('add-kid-panel').hidden;
  if (!$('add-kid-panel').hidden) $('new-kid-name').focus();
});
$('cancel-add-kid').addEventListener('click', () => {
  $('add-kid-panel').hidden = true;
});
$('add-kid-panel').addEventListener('submit', addKid);
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => switchView(button.dataset.view)));
document.querySelectorAll('[data-view-target]').forEach(button => button.addEventListener('click', () => switchView(button.dataset.viewTarget)));
document.querySelectorAll('[data-opponent-filter]').forEach(button => button.addEventListener('click', () => {
  opponentFilter = button.dataset.opponentFilter;
  document.querySelectorAll('[data-opponent-filter]').forEach(other => other.classList.toggle('active', other === button));
  render();
}));
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if ($('reports-view').classList.contains('active-view')) render();
  }, 150);
});
$('import-button').addEventListener('click', () => $('file-input').click());
$('source-import').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', event => {
  if (event.target.files[0]) importData(event.target.files[0]);
});

populateKids();
render();
