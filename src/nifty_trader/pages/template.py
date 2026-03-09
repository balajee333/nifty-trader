"""HTML template for VENOM Trading Journal GitHub Pages."""


def render_html(days_json: str) -> str:
    """Return complete self-contained index.html with embedded data.

    Args:
        days_json: JSON string of the days array (e.g., '[{...}, {...}]')
    """
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "<title>VENOM Trading Journal</title>\n"
        "<style>\n" + _CSS + "\n</style>\n"
        "</head>\n<body>\n"
        '<div id="app"></div>\n'
        "<script>\n"
        "const VENOM_DATA = " + days_json + ";\n"
        + _JS
        + "\n</script>\n</body>\n</html>"
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = r"""
:root {
  --bg: #0a0e27;
  --card: #1a1e3a;
  --card-hover: #222750;
  --text: #e0e0e0;
  --text-dim: #8888aa;
  --green: #00ff88;
  --red: #ff4466;
  --amber: #ffaa00;
  --blue: #4488ff;
  --orange: #ff8844;
  --gold: #ffd700;
  --border: rgba(255,255,255,0.06);
  --shadow: 0 4px 24px rgba(0,0,0,0.5);
  --radius: 10px;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  min-height: 100vh;
  line-height: 1.5;
}
#app { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }

/* ---- Header ---- */
.hdr { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 28px; }
.hdr-title {
  font-size: 1.6rem; font-weight: 700; color: #fff; letter-spacing: .5px;
  display: flex; align-items: center; gap: 8px; flex: 1 1 auto;
}
.hdr-title .icon { font-size: 1.4rem; }
.month-nav { display: flex; align-items: center; gap: 10px; }
.month-nav button {
  background: var(--card); border: 1px solid var(--border); color: var(--text);
  width: 32px; height: 32px; border-radius: 6px; cursor: pointer;
  font-size: 1rem; display: flex; align-items: center; justify-content: center;
  transition: background .2s;
}
.month-nav button:hover { background: var(--card-hover); }
.month-label { font-size: 1.1rem; font-weight: 600; color: #fff; min-width: 160px; text-align: center; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  background: var(--card); border: 1px solid var(--border); border-radius: 20px;
  padding: 4px 14px; font-size: .82rem; white-space: nowrap;
}
.chip b { font-weight: 700; }

/* ---- Calendar ---- */
.cal-hdr {
  display: grid; grid-template-columns: repeat(5,1fr); gap: 6px; margin-bottom: 4px;
}
.cal-hdr span {
  text-align: center; font-size: .75rem; font-weight: 600;
  color: var(--text-dim); text-transform: uppercase; padding: 4px 0;
}
.cal-grid {
  display: grid; grid-template-columns: repeat(5,1fr); gap: 6px;
}
.day-cell {
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 10px; min-height: 82px; cursor: pointer; transition: all .2s;
  position: relative; display: flex; flex-direction: column; gap: 4px;
}
.day-cell:hover { background: var(--card-hover); transform: translateY(-1px); }
.day-cell.empty { background: transparent; border-color: transparent; cursor: default; min-height: 0; }
.day-cell.empty:hover { transform: none; }
.day-cell.profit { border-left: 3px solid var(--green); background: rgba(0,255,136,0.04); }
.day-cell.loss { border-left: 3px solid var(--red); background: rgba(255,68,102,0.04); }
.day-cell.no-trade { border-left: 3px solid #555; }
.day-cell.today { box-shadow: 0 0 0 2px var(--blue); }
.day-cell.selected { box-shadow: 0 0 0 2px var(--amber); }
.day-num { font-weight: 700; font-size: .95rem; color: #fff; }
.day-signal {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-left: 6px;
}
.day-pnl { font-size: .85rem; font-weight: 600; margin-top: auto; }
.day-pnl.pos { color: var(--green); }
.day-pnl.neg { color: var(--red); }
.day-pnl.zero { color: var(--text-dim); }

/* ---- Detail Card ---- */
.detail-row {
  grid-column: 1 / -1;
  overflow: hidden;
  max-height: 0;
  transition: max-height .4s ease, opacity .3s ease;
  opacity: 0;
}
.detail-row.open { max-height: 2000px; opacity: 1; }
.detail-card {
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px; margin: 4px 0 10px; box-shadow: var(--shadow);
}
.detail-card h3 {
  font-size: .85rem; text-transform: uppercase; letter-spacing: 1px;
  color: var(--text-dim); margin-bottom: 10px; border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
}
.detail-card h3:not(:first-child) { margin-top: 18px; }
.snap-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr)); gap: 10px; }
.snap-item { font-size: .88rem; }
.snap-item .label { color: var(--text-dim); font-size: .78rem; }

/* badges */
.badge {
  display: inline-block; padding: 2px 10px; border-radius: 12px;
  font-size: .75rem; font-weight: 700; text-transform: uppercase; letter-spacing: .5px;
}
.badge-ce { background: rgba(68,136,255,.2); color: var(--blue); }
.badge-pe { background: rgba(255,136,68,.2); color: var(--orange); }
.badge-wait { background: rgba(136,136,136,.2); color: #aaa; }
.badge-no-trade { background: rgba(255,68,102,.15); color: var(--red); }
.badge-buy-ce { background: rgba(68,136,255,.2); color: var(--blue); }
.badge-buy-pe { background: rgba(255,136,68,.2); color: var(--orange); }

/* VIX mode badges */
.vix-full { background: rgba(0,255,136,.15); color: var(--green); }
.vix-selective { background: rgba(255,255,0,.12); color: #dddd00; }
.vix-caution { background: rgba(255,170,0,.15); color: var(--amber); }
.vix-restricted { background: rgba(255,136,68,.15); color: var(--orange); }
.vix-blocked { background: rgba(255,68,102,.15); color: var(--red); }

/* exit reason */
.exit-sl { background: rgba(255,68,102,.15); color: var(--red); }
.exit-trail { background: rgba(0,255,136,.15); color: var(--green); }
.exit-maxp { background: rgba(255,215,0,.15); color: var(--gold); }
.exit-time { background: rgba(136,136,136,.2); color: #aaa; }
.exit-force { background: rgba(255,68,102,.15); color: var(--red); }

/* grade */
.grade-aplus { background: rgba(255,215,0,.18); color: var(--gold); }
.grade-a { background: rgba(0,255,136,.15); color: var(--green); }
.grade-b { background: rgba(255,255,0,.12); color: #dddd00; }
.grade-c { background: rgba(255,170,0,.15); color: var(--amber); }
.grade-f { background: rgba(255,68,102,.15); color: var(--red); }

/* trade card */
.trade-card {
  background: rgba(255,255,255,.03); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; margin-bottom: 8px;
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
}
.trade-card .tc-field { font-size: .85rem; }
.trade-card .tc-label { color: var(--text-dim); font-size: .72rem; display: block; }
.trade-card .tc-pnl { font-size: 1rem; font-weight: 700; }

.rungs { display: inline-flex; gap: 4px; align-items: center; }
.rung {
  width: 10px; height: 10px; border-radius: 50%;
  border: 2px solid var(--green); display: inline-block;
}
.rung.hit { background: var(--green); }
.risk-free-badge {
  background: rgba(0,255,136,.12); color: var(--green);
  font-size: .68rem; font-weight: 700; padding: 1px 7px;
  border-radius: 8px; text-transform: uppercase;
}

/* confluence bar */
.conf-bar { display: inline-flex; gap: 2px; vertical-align: middle; }
.conf-seg {
  width: 14px; height: 8px; border-radius: 2px; background: rgba(255,255,255,.1);
}
.conf-seg.filled { background: var(--green); }

/* ---- Day Summary ---- */
.day-summary-pnl { font-size: 1.6rem; font-weight: 700; }

/* ---- Footer ---- */
.footer {
  margin-top: 36px; padding-top: 20px; border-top: 1px solid var(--border);
  display: flex; flex-wrap: wrap; align-items: flex-end; gap: 20px;
}
.footer .stats { display: flex; flex-wrap: wrap; gap: 16px; flex: 1; }
.footer .stat { font-size: .85rem; }
.footer .stat .label { color: var(--text-dim); font-size: .72rem; display: block; }
.sparkline-wrap { flex: 2 1 300px; min-width: 200px; }
.sparkline-wrap svg { width: 100%; height: 60px; }

/* responsive */
@media (max-width: 700px) {
  .cal-grid, .cal-hdr { grid-template-columns: repeat(5,1fr); gap: 4px; }
  .day-cell { padding: 6px; min-height: 64px; }
  .hdr { flex-direction: column; align-items: flex-start; }
  .trade-card { flex-direction: column; align-items: flex-start; }
}
"""

# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------
_JS = r"""
(function(){
"use strict";
const data = VENOM_DATA;
const app = document.getElementById('app');

// ---- Helpers ----
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const WKDAYS = ['Mon','Tue','Wed','Thu','Fri'];

function fmt(n, decimals) {
  if (n == null) return '--';
  const d = decimals != null ? decimals : 0;
  const s = Math.abs(n).toFixed(d).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return n < 0 ? '-' + s : s;
}
function pnlClass(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : 'zero'; }
function pnlColor(v) { return v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text-dim)'; }
function arrow(v) { return v > 0 ? '\u25B2' : v < 0 ? '\u25BC' : ''; }
function signalColor(s) {
  if (!s) return '#555';
  const m = {'buy_ce':'var(--blue)','buy_pe':'var(--orange)','wait':'#888','no_trade':'var(--red)'};
  return m[s.toLowerCase()] || '#555';
}
function signalBadge(s) {
  if (!s) return '';
  const c = {'buy_ce':'badge-buy-ce','buy_pe':'badge-buy-pe','wait':'badge-wait','no_trade':'badge-no-trade'};
  return '<span class="badge '+(c[s.toLowerCase()]||'badge-wait')+'">'+s.replace('_',' ')+'</span>';
}
function vixBadge(m) {
  if (!m) return '';
  const c = {'full':'vix-full','selective':'vix-selective','caution':'vix-caution','restricted':'vix-restricted','blocked':'vix-blocked'};
  return '<span class="badge '+(c[m.toLowerCase()]||'')+'">'+m.toUpperCase()+'</span>';
}
function exitBadge(r) {
  if (!r) return '';
  const c = {'sl_hit':'exit-sl','trail':'exit-trail','max_profit':'exit-maxp','time_stop':'exit-time','force_exit':'exit-force'};
  return '<span class="badge '+(c[r.toLowerCase()]||'')+'">'+r.replace('_',' ')+'</span>';
}
function gradeBadge(g) {
  if (!g) return '';
  const c = {'a+':'grade-aplus','a':'grade-a','b':'grade-b','c':'grade-c','f':'grade-f'};
  return '<span class="badge '+(c[g.toLowerCase()]||'')+'">'+g+'</span>';
}
function confBar(score) {
  let h = '<span class="conf-bar">';
  for (let i = 0; i < 5; i++) h += '<span class="conf-seg'+(i < score ? ' filled' : '')+'"></span>';
  return h + '</span>';
}
function rungDots(hits) {
  const levels = [20, 40, 70];
  const s = new Set(hits || []);
  let h = '<span class="rungs">';
  for (const l of levels) h += '<span class="rung'+(s.has(l) ? ' hit' : '')+'" title="'+l+'%"></span>';
  return h + '</span>';
}

// Build date index
const byDate = {};
data.forEach(d => { byDate[d.date] = d; });

// Determine date range
let curYear, curMonth;
if (data.length > 0) {
  const dates = data.map(d => new Date(d.date + 'T00:00:00')).sort((a,b) => b - a);
  curYear = dates[0].getFullYear();
  curMonth = dates[0].getMonth();
} else {
  const now = new Date();
  curYear = now.getFullYear();
  curMonth = now.getMonth();
}

let selectedDate = null;

function render() {
  const today = new Date();
  const todayStr = today.getFullYear()+'-'+String(today.getMonth()+1).padStart(2,'0')+'-'+String(today.getDate()).padStart(2,'0');

  // Month trading days
  const firstDay = new Date(curYear, curMonth, 1);
  const lastDay = new Date(curYear, curMonth + 1, 0);
  const tradingDays = [];
  for (let d = 1; d <= lastDay.getDate(); d++) {
    const dt = new Date(curYear, curMonth, d);
    const dow = dt.getDay();
    if (dow >= 1 && dow <= 5) {
      const ds = curYear+'-'+String(curMonth+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');
      tradingDays.push({ day: d, date: ds, dow: dow });
    }
  }

  // MTD stats
  const monthDays = tradingDays.map(t => byDate[t.date]).filter(Boolean);
  const mtdPnl = monthDays.reduce((s,d) => s + (d.daily_pnl || 0), 0);
  const tradeDays = monthDays.filter(d => d.trade_count > 0);
  const winDays = tradeDays.filter(d => d.daily_pnl > 0).length;
  const winRate = tradeDays.length > 0 ? Math.round(winDays / tradeDays.length * 100) : 0;
  const totalTrades = monthDays.reduce((s,d) => s + (d.trade_count || 0), 0);

  // Streak
  const sorted = data.slice().filter(d => d.trade_count > 0).sort((a,b) => a.date.localeCompare(b.date));
  let streak = 0;
  for (let i = sorted.length - 1; i >= 0; i--) {
    if (sorted[i].daily_pnl > 0) streak++;
    else if (sorted[i].daily_pnl < 0) { streak = -1 * (function(){ let c=0; for(let j=i;j>=0;j--){ if(sorted[j].daily_pnl<0)c++; else break;} return c;})(); break; }
    else break;
  }
  const streakStr = streak >= 0 ? streak + 'W' : Math.abs(streak) + 'L';

  // ---- Build HTML ----
  let html = '';

  // Header
  html += '<div class="hdr">';
  html += '<div class="hdr-title"><span class="icon">\uD83D\uDC0D</span> VENOM Trading Journal</div>';
  html += '<div class="month-nav">';
  html += '<button id="prev-month">\u25C0</button>';
  html += '<span class="month-label">' + MONTHS[curMonth] + ' ' + curYear + '</span>';
  html += '<button id="next-month">\u25B6</button>';
  html += '</div>';
  html += '<div class="chips">';
  html += '<span class="chip">MTD P&L: <b style="color:'+pnlColor(mtdPnl)+'">'+(mtdPnl>=0?'+':'')+fmt(mtdPnl)+'</b></span>';
  html += '<span class="chip">Win Rate: <b>'+winRate+'%</b></span>';
  html += '<span class="chip">Trades: <b>'+totalTrades+'</b></span>';
  html += '<span class="chip">Streak: <b style="color:'+(streak>=0?'var(--green)':'var(--red)')+'">'+streakStr+'</b></span>';
  html += '</div></div>';

  // Calendar header
  html += '<div class="cal-hdr">';
  WKDAYS.forEach(w => { html += '<span>' + w + '</span>'; });
  html += '</div>';

  // Calendar grid — group by weeks (Mon-Fri rows)
  html += '<div class="cal-grid">';

  // Leading empties for first week
  if (tradingDays.length > 0) {
    const firstDow = tradingDays[0].dow; // 1=Mon
    for (let i = 1; i < firstDow; i++) {
      html += '<div class="day-cell empty"></div>';
    }
  }

  let cellsInRow = tradingDays.length > 0 ? tradingDays[0].dow - 1 : 0;
  let pendingDetail = null;

  for (let idx = 0; idx < tradingDays.length; idx++) {
    const td = tradingDays[idx];
    const dd = byDate[td.date];
    const isToday = td.date === todayStr;
    const isSelected = td.date === selectedDate;

    let cls = 'day-cell';
    if (dd) {
      if (dd.trade_count > 0 && dd.daily_pnl > 0) cls += ' profit';
      else if (dd.trade_count > 0 && dd.daily_pnl < 0) cls += ' loss';
      else cls += ' no-trade';
    } else {
      cls += ' no-trade';
    }
    if (isToday) cls += ' today';
    if (isSelected) cls += ' selected';

    html += '<div class="'+cls+'" data-date="'+td.date+'">';
    html += '<div><span class="day-num">'+td.day+'</span>';
    if (dd && dd.signal) html += '<span class="day-signal" style="background:'+signalColor(dd.signal)+'"></span>';
    html += '</div>';
    if (dd && dd.daily_pnl != null && dd.trade_count > 0) {
      html += '<div class="day-pnl '+pnlClass(dd.daily_pnl)+'">'+(dd.daily_pnl>=0?'+':'')+fmt(dd.daily_pnl)+'</div>';
    } else if (dd && dd.skip_reason) {
      html += '<div class="day-pnl zero" style="font-size:.72rem">'+dd.skip_reason+'</div>';
    }
    html += '</div>';

    cellsInRow++;

    // Check if end of week row (Friday = dow 5) or last day
    const isEndOfRow = td.dow === 5 || idx === tradingDays.length - 1;

    if (isEndOfRow) {
      // Trailing empties
      if (td.dow < 5) {
        for (let i = td.dow; i < 5; i++) html += '<div class="day-cell empty"></div>';
      }

      // Insert detail row if a selected date is in this week row
      const weekStart = idx - (cellsInRow - 1) + (tradingDays.length > 0 ? tradingDays[0].dow - 1 : 0);
      let showDetail = false;
      if (selectedDate) {
        for (let j = idx - (td.dow - (tradingDays.length > 0 ? 1 : 1)); j >= 0 && j <= idx; j++) {
          if (j >= 0 && j < tradingDays.length && tradingDays[j].date === selectedDate) {
            showDetail = true; break;
          }
        }
        // Simpler: check if selectedDate dow falls in this row
        const selTd = tradingDays.find(t => t.date === selectedDate);
        if (selTd) {
          // Find the week of selTd vs current row
          const selWeekIdx = Math.floor(getGridPos(selTd, tradingDays) / 5);
          const curWeekIdx = Math.floor(getGridPos(td, tradingDays) / 5);
          showDetail = selWeekIdx === curWeekIdx;
        }
      }

      if (showDetail && selectedDate && byDate[selectedDate]) {
        html += '<div class="detail-row open">' + renderDetail(byDate[selectedDate]) + '</div>';
      }

      cellsInRow = 0;
    }
  }

  html += '</div>';

  // Footer
  html += renderFooter();

  app.innerHTML = html;

  // Event listeners
  document.getElementById('prev-month').addEventListener('click', () => {
    curMonth--; if (curMonth < 0) { curMonth = 11; curYear--; }
    selectedDate = null; render();
  });
  document.getElementById('next-month').addEventListener('click', () => {
    curMonth++; if (curMonth > 11) { curMonth = 0; curYear++; }
    selectedDate = null; render();
  });
  document.querySelectorAll('.day-cell[data-date]').forEach(el => {
    el.addEventListener('click', () => {
      const d = el.getAttribute('data-date');
      selectedDate = selectedDate === d ? null : d;
      render();
    });
  });
}

function getGridPos(td, tradingDays) {
  // Position in grid accounting for leading empties
  const firstDow = tradingDays[0].dow;
  const idx = tradingDays.indexOf(td);
  // Calculate grid column for this day
  // Week 1 starts at column (firstDow - 1)
  // We need the row index
  let col = 0, row = 0, curCol = firstDow - 1;
  for (let i = 0; i <= idx; i++) {
    if (i > 0) {
      const prevDow = tradingDays[i-1].dow;
      const curDow = tradingDays[i].dow;
      if (curDow <= prevDow) { row++; }
    }
  }
  return row * 5 + (td.dow - 1);
}

function renderDetail(d) {
  let h = '<div class="detail-card">';

  // Section 1: Market Snapshot
  h += '<h3>Market Snapshot</h3>';
  h += '<div class="snap-grid">';
  h += '<div class="snap-item"><span class="label">Nifty</span>'+fmt(d.nifty_open,1)+' \u2192 '+fmt(d.nifty_close,1)+' <span style="color:'+pnlColor(d.nifty_change_pct)+'">'+arrow(d.nifty_change_pct)+' '+fmt(Math.abs(d.nifty_change_pct),2)+'%</span></div>';
  h += '<div class="snap-item"><span class="label">VIX</span>'+fmt(d.vix,1)+' '+vixBadge(d.vix_mode)+'</div>';
  h += '<div class="snap-item"><span class="label">Day Type</span>'+(d.day_type||'--')+'</div>';
  h += '</div>';

  // Section 2: Signal Detection
  h += '<h3>Signal Detection</h3>';
  h += '<div class="snap-grid">';
  h += '<div class="snap-item"><span class="label">Signal</span>'+signalBadge(d.signal)+'</div>';
  if (d.signal_detail) h += '<div class="snap-item" style="grid-column:span 2"><span class="label">Detail</span>'+d.signal_detail+'</div>';
  h += '</div>';
  if (d.index_ohlc) {
    h += '<div class="snap-grid" style="margin-top:8px">';
    h += '<div class="snap-item"><span class="label">Open</span>'+fmt(d.index_ohlc.o,1)+'</div>';
    h += '<div class="snap-item"><span class="label">High</span>'+fmt(d.index_ohlc.h,1)+'</div>';
    h += '<div class="snap-item"><span class="label">Low</span>'+fmt(d.index_ohlc.l,1)+'</div>';
    h += '<div class="snap-item"><span class="label">Close</span>'+fmt(d.index_ohlc.c,1)+'</div>';
    h += '<div class="snap-item"><span class="label">Confluence</span>'+confBar(d.confluence_score||0)+' <span style="color:var(--text-dim);font-size:.78rem">'+(d.confluence_score||0)+'/5</span></div>';
    h += '</div>';
  }

  // Section 3: Trades
  if (d.trades && d.trades.length > 0) {
    h += '<h3>Trades</h3>';
    d.trades.forEach(t => {
      h += '<div class="trade-card">';
      h += '<span class="badge badge-'+(t.direction||'').toLowerCase()+'">'+(t.direction||'--')+'</span>';
      h += '<div class="tc-field"><span class="tc-label">Strike</span>'+fmt(t.strike)+'</div>';
      h += '<div class="tc-field"><span class="tc-label">Entry \u2192 Exit</span>'+(t.entry_time||'--')+' \u2192 '+(t.exit_time||'--')+'</div>';
      h += '<div class="tc-field"><span class="tc-label">Premium</span>'+fmt(t.entry_premium,1)+' \u2192 '+fmt(t.exit_premium,1)+'</div>';
      h += '<div class="tc-field tc-pnl" style="color:'+pnlColor(t.pnl)+'">'+(t.pnl>=0?'+':'')+fmt(t.pnl)+'</div>';
      h += exitBadge(t.exit_reason);
      h += ' '+gradeBadge(t.grade);
      h += '<div class="tc-field"><span class="tc-label">Trail Rungs</span>'+rungDots(t.rungs_hit)+'</div>';
      if (t.risk_free) h += '<span class="risk-free-badge">Risk-Free</span>';
      h += '</div>';
    });
  }

  // Section 4: Day Summary
  h += '<h3>Day Summary</h3>';
  h += '<div class="snap-grid">';
  h += '<div class="snap-item"><span class="label">Daily P&L</span><span class="day-summary-pnl" style="color:'+pnlColor(d.daily_pnl)+'">'+(d.daily_pnl>=0?'+':'')+fmt(d.daily_pnl)+'</span></div>';
  const healthColor = d.system_health === 'green' ? 'var(--green)' : d.system_health === 'yellow' ? 'var(--amber)' : d.system_health === 'red' ? 'var(--red)' : 'var(--text-dim)';
  h += '<div class="snap-item"><span class="label">System Health</span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:'+healthColor+';vertical-align:middle"></span> '+(d.system_health||'--')+'</div>';
  if (d.skip_reason) h += '<div class="snap-item"><span class="label">Skip Reason</span>'+d.skip_reason+'</div>';
  h += '</div>';

  h += '</div>';
  return h;
}

function renderFooter() {
  // Compute overall stats
  const allWithTrades = data.filter(d => d.trade_count > 0);
  const totalPnl = data.reduce((s,d) => s + (d.daily_pnl || 0), 0);
  const overallWins = allWithTrades.filter(d => d.daily_pnl > 0).length;
  const overallRate = allWithTrades.length > 0 ? Math.round(overallWins / allWithTrades.length * 100) : 0;

  let h = '<div class="footer">';

  // Equity sparkline
  h += '<div class="sparkline-wrap">';
  const sorted = data.slice().sort((a,b) => a.date.localeCompare(b.date));
  const last60 = sorted.slice(-60);
  if (last60.length > 1) {
    let cum = 0;
    const pts = last60.map(d => { cum += (d.daily_pnl || 0); return cum; });
    const minV = Math.min(0, ...pts);
    const maxV = Math.max(0, ...pts);
    const range = maxV - minV || 1;
    const w = 100; // viewBox width percentage
    const ht = 55;
    const coords = pts.map((v, i) => {
      const x = (i / (pts.length - 1)) * 100;
      const y = ht - ((v - minV) / range) * (ht - 5);
      return x.toFixed(1)+','+y.toFixed(1);
    });
    // Zero line
    const zeroY = (ht - ((0 - minV) / range) * (ht - 5)).toFixed(1);
    const lastPt = pts[pts.length - 1];
    const lineColor = lastPt >= 0 ? 'var(--green)' : 'var(--red)';
    h += '<svg viewBox="0 0 100 60" preserveAspectRatio="none">';
    h += '<line x1="0" y1="'+zeroY+'" x2="100" y2="'+zeroY+'" stroke="rgba(255,255,255,.1)" stroke-width="0.3"/>';
    h += '<polyline fill="none" stroke="'+lineColor+'" stroke-width="0.8" points="'+coords.join(' ')+'"/>';
    // Gradient fill
    h += '<defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+lineColor+'" stop-opacity="0.2"/><stop offset="100%" stop-color="'+lineColor+'" stop-opacity="0"/></linearGradient></defs>';
    h += '<polygon fill="url(#sg)" points="0,'+zeroY+' '+coords.join(' ')+' 100,'+zeroY+'"/>';
    h += '</svg>';
  }
  h += '</div>';

  h += '<div class="stats">';
  h += '<div class="stat"><span class="label">Days Tracked</span><b>'+data.length+'</b></div>';
  h += '<div class="stat"><span class="label">Overall Win Rate</span><b>'+overallRate+'%</b></div>';
  h += '<div class="stat"><span class="label">Total P&L</span><b style="color:'+pnlColor(totalPnl)+'">'+(totalPnl>=0?'+':'')+fmt(totalPnl)+'</b></div>';
  h += '</div></div>';
  return h;
}

render();
})();
"""
