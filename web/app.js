'use strict';

const CAT_COLORS = {
  '学习': '#4cc97a', '工作': '#5aa9e6', '娱乐': '#f2789f', '社交': '#9d7bea',
  '游戏': '#f2a65a', '购物': '#4dd0c1', '闲置': '#6b7a8d', '其他': '#8fa6bf'
};
const OFF_COLOR = '#f2789f';
// 休息时段单独一个中性色（青灰）。不用绿也不用红：休息既不是"在状态"
// 也不是"分心"，而且它的判定不计入统计，用彩色会让人以为算进了专注率。
const BREAK_COLOR = '#5f7d8c';
const NS = 'http://www.w3.org/2000/svg';

let busy = false;

// ---------- 小工具 ----------
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function svgEl(tag, attrs) {
  const e = document.createElementNS(NS, tag);
  for (const k in (attrs || {})) e.setAttribute(k, attrs[k]);
  return e;
}
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  if (h) return h + ' 小时 ' + String(m).padStart(2, '0') + ' 分';
  if (m) return m + ' 分 ' + String(sec % 60).padStart(2, '0') + ' 秒';
  return sec + ' 秒';
}
function fmtClock(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso.slice(11, 19);
  return d.toTimeString().slice(0, 8);
}
function pct(x) { return Math.round((x || 0) * 100); }
async function api(path, opts) {
  const r = await fetch(path, Object.assign({ cache: 'no-store' }, opts || {}));
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

// ---------- 顶部状态 ----------
function renderStatus(d) {
  const dot = document.getElementById('dot');
  const txt = document.getElementById('statusText');
  const state = d.state || (d.running ? 'running' : 'stopped');
  const pids = (d.pids || []).join(', ');
  dot.className = 'dot ' + (state === 'stopped' ? 'off' : state === 'paused' ? 'paused' : 'on');
  txt.textContent = state === 'running' ? '监督中（PID ' + pids + '）'
    : state === 'paused' ? '已暂停（进程待命）'
    : '未在监督';
  document.getElementById('updated').textContent = '更新于 ' + new Date().toLocaleTimeString();
}

function renderWarn(d) {
  const box = document.getElementById('warnBox');
  box.innerHTML = '';
  const msgs = [];
  if (!d.key_ok) msgs.push('没有找到 API key，判定会失败。请检查 ' + (d.key_hint || 'DEEPSEEK_API_KEY') + '。');
  if (d.today.checks === 0 && d.running) msgs.push('还没产生判定记录，等第一个周期（约 ' + d.interval_sec + ' 秒）即可。');
  for (const m of msgs) box.appendChild(el('div', 'warn', m));
}

// ---------- 概览卡片 ----------
function renderCards(d) {
  const t = d.today;
  const wrap = document.getElementById('cards');
  wrap.innerHTML = '';

  const focus = t.checks ? pct(t.on_task_rate) : 0;
  const cardFocus = el('div', 'card');
  cardFocus.appendChild(el('div', 'sub', '今日专注率'));
  const m1 = el('div', 'metric');
  m1.appendChild(document.createTextNode(focus + ' %'));
  cardFocus.appendChild(m1);
  cardFocus.appendChild(el('div', 'sub', '在状态 ' + fmtDur(t.on_task_sec) + ' · 分心 ' + fmtDur(t.off_task_sec)));
  wrap.appendChild(cardFocus);

  const c2 = el('div', 'card');
  c2.appendChild(el('div', 'sub', '覆盖时长'));
  c2.appendChild(el('div', 'metric', fmtDur(t.span_sec)));
  c2.appendChild(el('div', 'sub', '共 ' + t.checks + ' 次判定' + (t.skipped ? ' · 跳过 ' + t.skipped + ' 次' : '')));
  wrap.appendChild(c2);

  const c3 = el('div', 'card');
  c3.appendChild(el('div', 'sub', '分心次数'));
  c3.appendChild(el('div', 'metric', String(t.off_events.length)));
  c3.appendChild(el('div', 'sub', t.off_events.length ? '最近一次 ' + fmtClock(t.off_events[t.off_events.length - 1].ts) : '今天没分心，稳'));
  wrap.appendChild(c3);

  const c4 = el('div', 'card');
  c4.appendChild(el('div', 'sub', '今日花费'));
  c4.appendChild(el('div', 'metric', '$' + (t.cost_usd || 0).toFixed(4)));
  c4.appendChild(el('div', 'sub', '平均延迟 ' + (t.avg_latency_ms || 0) + ' ms' + (t.errors ? ' · 失败 ' + t.errors : '')));
  wrap.appendChild(c4);

  // 此刻在做什么（看历史日期时标题会改成"当天最后一条"）
  const card = el('div', 'card');
  card.style.gridColumn = '1 / -1';
  card.id = 'nowCard';
  card.appendChild(el('h2', null, '现在'));
  const last = t.last;
  if (!last) {
    card.appendChild(el('div', 'empty', '还没有判定记录'));
  } else {
    const now = el('div', 'now');
    // 左侧角色头像：和提醒弹窗是同一张脸，一眼能对上"刚才弹的是哪个"
    const avWrap = el('div', 'avwrap');
    avWrap.appendChild(avatarEl(last.avatar, 'lg'));
    const lab = AVATAR_LABEL[last.avatar] || AVATAR_LABEL.general;
    avWrap.appendChild(el('div', 'avname', lab[0]));
    now.appendChild(avWrap);

    const right = el('div');
    right.style.flex = '1';
    right.style.minWidth = '0';
    right.appendChild(el('span', 'badge',
      (last.on_task ? '在状态 · ' : '分心 · ') + (last.category || '其他')));
    right.appendChild(el('div', 'txt', last.activity || '（无描述）'));
    const b = el('div', 'basis', '依据：' + (last.basis || '—'));
    right.appendChild(b);
    const meta = el('div', 'basis',
      fmtClock(last.ts) + ' · ' + (last.process || '未知程序') +
      ' · 置信度 ' + pct(last.confidence) + '%' +
      (last.process === '' ? '' : ' · 花费 $' + (last.cost_usd || 0).toFixed(4)));
    right.appendChild(meta);
    now.appendChild(right);
    card.appendChild(now);
  }
  wrap.appendChild(card);
}

// 时间轴/周图都按容器实际像素宽画：viewBox 宽度 = 测得宽度，SVG 也按这个像素尺寸渲染，
// 再配 max-width:100% 兜底（容器变窄时浏览器等比缩小，坐标仍然和时间一致）。
function containerWidth(hostEl, min) {
  return Math.max(min, Math.round(hostEl.clientWidth || 0));
}

function sizeSvg(svg, W, H) {
  svg.setAttribute('width', W);
  svg.setAttribute('height', H);
  svg.style.width = W + 'px';
  svg.style.maxWidth = '100%';
  svg.style.height = H + 'px';
}

// ---------- 时间轴 ----------
// 时间窗状态：{from, to} 为 null 表示"全天自动"（按当天首末条记录自适应）。
// 数据本身一直是整天，缩放只是前端过滤，不改后端。
let tlRange = null;          // {from: ms, to: ms} 或 null
let tlBrush = null;          // 拖选中的临时区间 {from, to}（毫秒）
let tlData = null;           // 缓存最近一次的数据，供重绘用
let tlDay = null;            // 正在看哪一天（YYYY-MM-DD）；null = 后端默认（今天）

// 当前视图是不是"今天"（决定要不要画"现在"虚线、提示怎么写）
function tlIsToday() {
  return !tlData || tlData.is_today !== false;
}

function tlItemsAll() {
  return (tlData && tlData.today && tlData.today.timeline) || [];
}

function tlBounds() {
  const items = tlItemsAll();
  if (!items.length) return null;
  const t0 = new Date(items[0].ts).getTime();
  const last = items[items.length - 1];
  const t1 = new Date(last.ts).getTime() + (last.sec || 60) * 1000;
  return { t0, t1 };
}

// 选一个"整齐"的刻度间隔：目标是屏幕上每格约 60~110px
function tlTickStep(span, width) {
  const steps = [60e3, 2 * 60e3, 5 * 60e3, 10 * 60e3, 15 * 60e3, 30 * 60e3,
                 3600e3, 2 * 3600e3, 3 * 3600e3, 6 * 3600e3, 12 * 3600e3, 24 * 3600e3];
  for (const s of steps) {
    if (span / s * 80 <= width) return s;
  }
  return steps[steps.length - 1];
}

function tlFmtTick(t, step) {
  const d = new Date(t);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  if (step >= 3600e3) return hh + ':00';
  return hh + ':' + mm;
}

// 日期下拉：列出有记录的日子（后端给 available_days）
function tlBuildDays(d) {
  const sel = document.getElementById('tlDay');
  if (!sel || !d) return;
  const days = d.available_days || [];
  const want = d.view_day || '';
  const sig = days.join(',') + '|' + want;
  if (sel.dataset.sig === sig) return;          // 没变化就不重建，避免打断用户操作
  sel.dataset.sig = sig;
  sel.innerHTML = '';
  const todayStr = new Date().toLocaleDateString('sv-SE');   // 本地时区的 YYYY-MM-DD
  for (const ds of days) {
    const o = document.createElement('option');
    o.value = ds;
    const label = ds + (ds === todayStr ? '（今天）' : '');
    o.textContent = label;
    if (ds === want) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => {
    tlDay = sel.value;
    tlRange = null;          // 换天就回到全天，避免拿着昨天的窗口看今天
    syncTlInputs();
    tlMarkPreset(null);
    clearTlWarn();
    refresh();
  };
}

// 预设区间定义（分钟）；null 表示全天
const TL_PRESETS = [
  ['全天', null],
  ['最近 1 小时', 60],
  ['最近 3 小时', 180],
  ['最近 6 小时', 360],
  ['最近 12 小时', 720],
];

function tlBuildPresets() {
  const host = document.getElementById('tlPresets');
  if (!host) return;
  host.innerHTML = '';
  for (const [label, mins] of TL_PRESETS) {
    const b = el('button', mins === null && tlRange === null ? 'on' : null, label);
    b.dataset.mins = mins === null ? '' : String(mins);
    b.onclick = () => {
      const bd = tlBounds();
      if (!bd) return;
      if (mins === null) {
        tlRange = null;
      } else {
        // 锚点：看今天时是"现在"，看历史日期时是那天最后一条记录。
        // 否则在历史日期上点"最近 1 小时"会得到一段空窗口（数据早就结束了）。
        const anchor = tlIsToday() ? Math.max(bd.t1, Date.now()) : bd.t1;
        tlRange = { from: Math.max(bd.t0, anchor - mins * 60e3), to: anchor };
      }
      clearTlWarn();
      syncTlInputs();
      renderTimeline(tlData);
    };
    host.appendChild(b);
  }
}

function tlMarkPreset(mins) {
  const host = document.getElementById('tlPresets');
  if (!host) return;
  host.querySelectorAll('button').forEach(btn => {
    const m = btn.dataset.mins === '' ? null : Number(btn.dataset.mins);
    btn.classList.toggle('on', m === mins);
  });
}

function syncTlInputs() {
  const from = document.getElementById('tlFrom');
  const to = document.getElementById('tlTo');
  if (!from || !to) return;
  if (!tlRange) { from.value = ''; to.value = ''; return; }
  from.value = msToTimeInput(tlRange.from);
  to.value = msToTimeInput(tlRange.to);
}

function msToTimeInput(ms) {
  const d = new Date(ms);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

// 把 "HH:MM" 解释成当天的本地时间；跨零点（结束早于开始）时把结束挪到次日
function timeInputToMs(value, dayMs, isEnd) {
  const m = /^(\d{1,2}):(\d{2})$/.exec((value || '').trim());
  if (!m) return null;
  const d = new Date(dayMs);
  d.setHours(Number(m[1]), Number(m[2]), 0, 0);
  return d.getTime();
}

function tlApplyCustom() {
  const bd = tlBounds();
  if (!bd) return;
  const f = timeInputToMs(document.getElementById('tlFrom').value, bd.t0, false);
  const t = timeInputToMs(document.getElementById('tlTo').value, bd.t0, true);
  if (f === null || t === null) {
    setTlWarn('请把起止时间都填上（HH:MM）');
    return;
  }
  let to = t;
  if (to <= f) to += 86400e3;            // 跨零点，例如 22:00 → 02:00
  if (to - f < 60e3) {
    setTlWarn('区间太短了，至少 1 分钟');
    return;
  }
  tlRange = { from: f, to };
  tlMarkPreset(undefined);
  clearTlWarn();
  renderTimeline(tlData);
}

function setTlHint(text, warn) {
  const h = document.getElementById('tlHint');
  if (!h) return;
  h.textContent = text || '';
  h.style.color = warn ? 'var(--amber)' : 'var(--faint)';
}

// 校验类提示要能"顶住"5 秒一次的自动重绘：
// 之前直接写 DOM，下一次 refresh 重绘时间轴就把它冲掉了，用户根本看不到。
// 这里把警告存下来，renderTimeline 会优先显示它，用户下一次操作时清掉。
let tlHintOverride = null;

function setTlWarn(text) {
  tlHintOverride = text || null;
  setTlHint(text, true);
}

function clearTlWarn() {
  tlHintOverride = null;
}

function renderTimeline(d) {
  if (d) tlData = d;
  const data = tlData;
  const host = document.getElementById('timeline');
  if (!host || !data) return;
  host.innerHTML = '';

  const all = tlItemsAll();
  const bd = tlBounds();
  if (!bd) {
    document.getElementById('tlTag').textContent = '';
    host.appendChild(el('div', 'empty', '今天还没有判定记录'));
    document.getElementById('tlLegend').innerHTML = '';
    setTlHint('还没有数据可看');
    renderOffList(data, null);
    return;
  }

  // 可见区间：未指定则用全天实际跨度
  const vis = tlRange || { from: bd.t0, to: bd.t1 };
  const span = Math.max(60e3, vis.to - vis.from);
  const items = all.filter(it => {
    const s = new Date(it.ts).getTime();
    return s + (it.sec || 60) * 1000 >= vis.from && s <= vis.to;
  });

  const W = containerWidth(host, 900);
  const H = 118, padL = 6, padR = 6, padT = 10;
  const x = ms => padL + (ms - vis.from) / span * (W - padL - padR);

  const svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H });
  sizeSvg(svg, W, H);
  svg.dataset.kind = 'timeline';

  // 背景刻度（间隔自适应：放大到分钟级时不再只画整点）
  const step = tlTickStep(span, W);
  const firstFloor = Math.floor(vis.from / step) * step;
  for (let t = firstFloor; t <= vis.to; t += step) {
    if (t < vis.from) continue;
    const px = x(t);
    svg.appendChild(svgEl('line', { x1: px, y1: padT, x2: px, y2: H - 30, stroke: '#22303f', 'stroke-width': 1 }));
    const label = svgEl('text', { x: px + 3, y: H - 16, fill: '#5d6f85', 'font-size': 11 });
    label.textContent = tlFmtTick(t, step);
    svg.appendChild(label);
  }

  // 每个判定一段，高度按专注/分心区分
  for (const it of items) {
    const start = new Date(it.ts).getTime();
    const end = start + (it.sec || 60) * 1000;
    const cx0 = Math.max(x(start), padL), cx1 = Math.min(x(end), W - padR);
    const w = Math.max(2, cx1 - cx0);
    // 三态：休息 / 在状态 / 分心。
    // 休息必须单独画——它的判定不计入统计（后端 aggregate 会排除），
    // 若照"在状态"着色，时间轴看起来就像一直在学习，而且总时长与
    // 概览卡的"在状态+分心"对不上（实测差过 594s，是一条 long_break）。
    const isBreak = !!it.is_break;
    const onTask = it.on_task;
    const color = isBreak ? BREAK_COLOR
      : (onTask ? (CAT_COLORS[it.category] || '#4cc97a') : OFF_COLOR);
    const h = onTask && !isBreak ? 34 : 20;
    const y = padT + (onTask && !isBreak ? 0 : 40);
    const rect = svgEl('rect', {
      x: cx0, y: y, width: w, height: h, rx: 3,
      fill: color, opacity: isBreak ? .75 : (onTask ? .92 : .85)
    });
    const tip = svgEl('title');
    tip.textContent = fmtClock(it.ts) + '（' + fmtDur(it.sec) + '）\n' +
      (isBreak ? '休息（不计入统计）' : (it.on_task ? '在状态' : '分心')) +
      ' · ' + (it.category || '') + '\n' +
      (it.activity || '') + '\n依据：' + (it.basis || '');
    rect.appendChild(tip);
    svg.appendChild(rect);
  }

  // 轴
  svg.appendChild(svgEl('line', { x1: padL, y1: H - 30, x2: W - padR, y2: H - 30, stroke: '#2a3a4d', 'stroke-width': 1 }));
  const labOn = svgEl('text', { x: padL, y: H - 4, fill: '#4cc97a', 'font-size': 11 });
  labOn.textContent = '上行：在状态（按类别着色）';
  const labOff = svgEl('text', { x: 220, y: H - 4, fill: OFF_COLOR, 'font-size': 11 });
  labOff.textContent = '下行：分心 / 休息';
  svg.appendChild(labOn); svg.appendChild(labOff);

  // 缩放到较小区间时，画一条"现在"的位置线，方便对照（只看今天时才有意义）
  const now = Date.now();
  if (tlIsToday() && now >= vis.from && now <= vis.to) {
    const px = x(now);
    svg.appendChild(svgEl('line', { x1: px, y1: padT, x2: px, y2: H - 30, stroke: '#78aaeb', 'stroke-width': 1, 'stroke-dasharray': '3 3', opacity: .7 }));
  }

  host.appendChild(svg);

  // ---- 交互：拖选区间缩放 + 滚轮缩放 ----
  const brushRect = svgEl('rect', { class: 'tlbrush', x: 0, y: 0, width: 0, height: 0, visibility: 'hidden' });
  svg.appendChild(brushRect);

  const msAt = evt => {
    const r = svg.getBoundingClientRect();
    const px = Math.min(Math.max(evt.clientX - r.left, padL), W - padR);
    return vis.from + (px - padL) / (W - padL - padR) * span;
  };

  let dragFrom = null;
  svg.addEventListener('pointerdown', evt => {
    if (evt.button !== 0) return;
    dragFrom = msAt(evt);
    tlBrush = { from: dragFrom, to: dragFrom };
    svg.setPointerCapture(evt.pointerId);
  });
  svg.addEventListener('pointermove', evt => {
    if (dragFrom === null) return;
    tlBrush = { from: Math.min(dragFrom, msAt(evt)), to: Math.max(dragFrom, msAt(evt)) };
    const a = x(tlBrush.from), b = x(tlBrush.to);
    brushRect.setAttribute('x', a);
    brushRect.setAttribute('width', Math.max(1, b - a));
    brushRect.setAttribute('y', padT);
    brushRect.setAttribute('height', H - 30 - padT);
    brushRect.setAttribute('visibility', 'visible');
    setTlHint('松手即缩放到 ' + msToTimeInput(tlBrush.from) + ' – ' + msToTimeInput(tlBrush.to));
  });
  const endDrag = evt => {
    if (dragFrom === null) return;
    const sel = tlBrush;
    dragFrom = null;
    brushRect.setAttribute('visibility', 'hidden');
    if (!sel || sel.to - sel.from < 60e3) {   // 单击（或几乎没拖动）：当作取消
      tlBrush = null;
      renderTimeline(null);
      return;
    }
    tlRange = sel;
    tlBrush = null;
    tlMarkPreset(undefined);
    clearTlWarn();
    renderTimeline(null);
  };
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);

  // 滚轮缩放：以光标位置为锚点
  svg.addEventListener('wheel', evt => {
    evt.preventDefault();
    const anchor = msAt(evt);
    const factor = evt.deltaY > 0 ? 1.25 : 0.8;
    let from = anchor - (anchor - vis.from) * factor;
    let to = anchor + (vis.to - anchor) * factor;
    // 不超出当天数据的边界，也不窄于 1 分钟
    const minSpan = 60e3;
    if (to - from < minSpan) {
      const mid = (from + to) / 2;
      from = mid - minSpan / 2; to = mid + minSpan / 2;
    }
    from = Math.max(from, bd.t0 - 3600e3);
    to = Math.min(to, bd.t1 + 3600e3);
    tlRange = { from, to };
    tlMarkPreset(undefined);
    clearTlWarn();
    renderTimeline(null);
  }, { passive: false });

  // ---- 标签与提示 ----
  const shown = items.length;
  document.getElementById('tlTag').textContent =
    `${msToTimeInput(vis.from)}–${msToTimeInput(vis.to)}｜${shown} 段`;
  if (tlHintOverride) {
    setTlHint(tlHintOverride, true);          // 校验提示优先，不被重绘冲掉
  } else if (!tlRange) {
    setTlHint(`${all.length} 段都在视图内（自动铺满当天）`);
  } else {
    setTlHint(`显示 ${shown}/${all.length} 段｜在此区间内拖动可再放大，滚轮缩放`);
  }
  // 图例
  const cats = [...new Set(items.filter(i => i.on_task && !i.is_break)
    .map(i => i.category || '其他'))];
  const legend = document.getElementById('tlLegend');
  legend.innerHTML = '';
  for (const c of cats) {
    const s = document.createElement('span');
    const i = document.createElement('i');
    i.style.background = CAT_COLORS[c] || '#4cc97a';
    s.appendChild(i);
    s.appendChild(document.createTextNode(c));
    legend.appendChild(s);
  }
  const mkLegend = (color, text) => {
    const s = document.createElement('span');
    const i = document.createElement('i');
    i.style.background = color;
    s.appendChild(i);
    s.appendChild(document.createTextNode(text));
    legend.appendChild(s);
  };
  // 只有真的出现过休息时段才显示这一项，否则图例里多一个用不到的颜色
  if (items.some(i => i.is_break)) mkLegend(BREAK_COLOR, '休息（不计入统计）');
  mkLegend(OFF_COLOR, '分心');

  // 分心明细：可选跟随当前区间
  const follow = document.getElementById('offFollow');
  renderOffList(data, (follow && follow.checked) ? vis : null);
}

// ---------- 分心记录明细 ----------
// 可选 range：只显示落在该时间区间内的记录（跟随时间轴缩放时用）
function renderOffList(d, range) {
  const host = document.getElementById('offlist');
  host.innerHTML = '';
  const all = (d.today.off_events || []);
  const evs = (range
    ? all.filter(e => {
        const t = new Date(e.ts).getTime();
        return t >= range.from && t <= range.to;
      })
    : all).slice().reverse();

  const tag = document.getElementById('offTag');
  if (tag) tag.textContent = range ? `${evs.length}/${all.length} 条` : (all.length ? all.length + ' 条' : '');

  if (!evs.length) {
    host.appendChild(el('div', 'sub', range ? '这个时间段内没有分心记录。' : '今天还没有分心记录。'));
    return;
  }
  const head = el('div', 'sub', range
    ? `该区间分心 ${evs.length} 条（共 ${all.length} 条，最新在前）`
    : '分心记录（' + evs.length + ' 条，最新在前）');
  head.style.marginBottom = '4px';
  host.appendChild(head);
  for (const e of evs.slice(0, 12)) {
    const row = el('div', 'offrow');
    row.appendChild(avatarEl(e.avatar, 'sm'));
    row.appendChild(el('span', 't', fmtClock(e.ts)));
    const c = el('span', 'c');
    c.appendChild(el('span', 'pill off', e.category || '其他'));
    row.appendChild(c);
    const a = el('div', 'a');
    a.appendChild(el('div', null, e.activity || ''));
    if (e.basis) a.appendChild(el('div', 'b', '依据：' + e.basis));
    row.appendChild(a);
    host.appendChild(row);
  }
}

// ---------- 环形图 ----------
function renderDonut(d) {
  const host = document.getElementById('donut');
  host.innerHTML = '';
  const cats = d.today.cat_sec || [];
  if (!cats.length) {
    host.appendChild(el('div', 'empty', '暂无数据'));
    document.getElementById('donutLegend').innerHTML = '';
    return;
  }
  const total = cats.reduce((s, c) => s + c.sec, 0);
  const SIZE = 190, R = 74, r = 46, cx = SIZE / 2, cy = SIZE / 2;
  const svg = svgEl('svg', { viewBox: '0 0 ' + SIZE + ' ' + SIZE });
  svg.style.maxWidth = SIZE + 'px';
  svg.style.margin = '0 auto';

  let acc = -Math.PI / 2;
  for (const c of cats) {
    const ang = c.sec / total * Math.PI * 2;
    const a0 = acc, a1 = acc + ang;
    acc = a1;
    const large = ang > Math.PI ? 1 : 0;
    const p = (rad, a) => [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
    const [x0, y0] = p(R, a0), [x1, y1] = p(R, a1), [x2, y2] = p(r, a1), [x3, y3] = p(r, a0);
    const path = svgEl('path', {
      d: `M ${x0} ${y0} A ${R} ${R} 0 ${large} 1 ${x1} ${y1} L ${x2} ${y2} A ${r} ${r} 0 ${large} 0 ${x3} ${y3} Z`,
      fill: CAT_COLORS[c.cat] || '#8fa6bf', stroke: '#18222f', 'stroke-width': 1.5
    });
    const tip = svgEl('title');
    tip.textContent = c.cat + ' · ' + fmtDur(c.sec) + '（' + Math.round(c.sec / total * 100) + '%）';
    path.appendChild(tip);
    svg.appendChild(path);
  }
  const t1 = svgEl('text', { x: cx, y: cy - 2, 'text-anchor': 'middle', fill: '#e8eef6', 'font-size': 19, 'font-weight': 600 });
  t1.textContent = pct(d.today.on_task_rate) + '%';
  const t2 = svgEl('text', { x: cx, y: cy + 17, 'text-anchor': 'middle', fill: '#8fa6bf', 'font-size': 11 });
  t2.textContent = '在状态占比';
  svg.appendChild(t1); svg.appendChild(t2);
  host.appendChild(svg);

  const lg = document.getElementById('donutLegend');
  lg.innerHTML = '';
  for (const c of cats) {
    const s = el('span');
    const i = el('i'); i.style.background = CAT_COLORS[c.cat] || '#8fa6bf';
    s.appendChild(i);
    s.appendChild(document.createTextNode(c.cat + ' ' + fmtDur(c.sec)));
    lg.appendChild(s);
  }
}

// ---------- 近 7 天 ----------
function renderWeek(d) {
  const host = document.getElementById('week');
  host.innerHTML = '';
  const days = d.days || [];
  if (!days.length) { host.appendChild(el('div', 'empty', '暂无历史')); return; }

  const W = containerWidth(host, 420);
  const H = 150, padL = 40, padB = 26, padT = 8;
  const maxSec = Math.max(600, ...days.map(x => x.on_task_sec + x.off_task_sec));
  const bw = (W - padL - 8) / days.length;
  const svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H });
  sizeSvg(svg, W, H);
  svg.dataset.kind = 'week';

  // 网格
  for (let k = 0; k <= 2; k++) {
    const v = maxSec * k / 2;
    const y = H - padB - (v / maxSec) * (H - padB - padT);
    svg.appendChild(svgEl('line', { x1: padL, y1: y, x2: W - 8, y2: y, stroke: '#22303f', 'stroke-width': 1 }));
    const t = svgEl('text', { x: padL - 6, y: y + 4, 'text-anchor': 'end', fill: '#5d6f85', 'font-size': 10 });
    t.textContent = (v / 3600).toFixed(1) + 'h';
    svg.appendChild(t);
  }

  days.forEach((day, i) => {
    const x = padL + i * bw + bw * 0.18;
    const w = bw * 0.64;
    const hOn = (day.on_task_sec / maxSec) * (H - padB - padT);
    const hOff = (day.off_task_sec / maxSec) * (H - padB - padT);
    const yOff = H - padB - hOff;
    const yOn = yOff - hOn;
    if (!day.checks) {
      const t = svgEl('text', { x: x + w / 2, y: H - padB - 6, 'text-anchor': 'middle', fill: '#3d4d60', 'font-size': 10 });
      t.textContent = '无';
      svg.appendChild(t);
    } else {
      const rOn = svgEl('rect', { x: x, y: yOn, width: w, height: Math.max(1, hOn), rx: 3, fill: '#4cc97a' });
      const tipOn = svgEl('title');
      tipOn.textContent = day.date + ' 在状态 ' + fmtDur(day.on_task_sec) + ' · 分心 ' + fmtDur(day.off_task_sec) +
        ' · 专注率 ' + pct(day.on_task_rate) + '% · ' + day.checks + ' 次判定';
      rOn.appendChild(tipOn);
      svg.appendChild(rOn);
      if (hOff > 0.5) {
        const rOff = svgEl('rect', { x: x, y: yOff, width: w, height: Math.max(1, hOff), rx: 3, fill: '#f2789f' });
        const tipOff = svgEl('title');
        tipOff.textContent = day.date + ' 分心 ' + fmtDur(day.off_task_sec);
        rOff.appendChild(tipOff);
        svg.appendChild(rOff);
      }
    }
    const lab = svgEl('text', { x: x + w / 2, y: H - 8, 'text-anchor': 'middle', fill: '#8fa6bf', 'font-size': 10 });
    lab.textContent = day.date.slice(5);
    svg.appendChild(lab);
  });
  host.appendChild(svg);
}

// ---------- 分心来源 ----------
function renderProcs(d) {
  const host = document.getElementById('procs');
  host.innerHTML = '';
  const procs = d.today.proc_off || [];
  if (!procs.length) { host.appendChild(el('div', 'empty', '今天没有分心记录 🎉')); return; }
  const max = Math.max(...procs.map(p => p.sec));
  for (const p of procs) {
    const row = el('div', 'kv');
    const name = el('span', null, p.name);
    const right = el('span', null, fmtDur(p.sec));
    row.appendChild(name); row.appendChild(right);
    host.appendChild(row);
    const bar = el('div');
    bar.style.cssText = 'height:6px;border-radius:4px;background:#22303f;margin:2px 0 8px';
    const fill = el('div');
    fill.style.cssText = 'height:6px;border-radius:4px;background:' + OFF_COLOR + ';width:' + (p.sec / max * 100) + '%';
    bar.appendChild(fill);
    host.appendChild(bar);
  }
}

// ---------- 概况 ----------
function renderMeta(d) {
  const host = document.getElementById('meta');
  host.innerHTML = '';
  const t = d.today;
  const rows = [
    ['判定间隔', d.interval_sec + ' 秒'],
    ['累计判定', t.checks + ' 次'],
    ['失败 / 跳过', t.errors + ' / ' + t.skipped + ' 次'],
    ['平均延迟', (t.avg_latency_ms || 0) + ' ms'],
    ['今日 tokens', (t.tokens_in || 0) + ' 入 / ' + (t.tokens_out || 0) + ' 出'],
    ['今日花费', '$' + (t.cost_usd || 0).toFixed(4)],
    ['截图保存', d.save_shots ? '已开启（data/shots）' : '未保存（仅内存）'],
    ['模型', d.model],
  ];
  for (const [k, v] of rows) {
    const row = el('div', 'kv');
    row.appendChild(el('span', null, k));
    row.appendChild(el('span', null, String(v)));
    host.appendChild(row);
  }
}

// ---------- 最近判定 ----------
function renderRecent(d) {
  const tbl = document.getElementById('recent');
  tbl.innerHTML = '';
  const recs = (d.today.recent || []).slice().reverse();
  document.getElementById('recentTag').textContent = d.today.checks ? '共 ' + d.today.checks + ' 次' : '';
  if (!recs.length) {
    tbl.appendChild(el('div', 'empty', '暂无记录'));
    return;
  }
  const thead = el('thead');
  const tr = el('tr');
  ['', '时间', '判定', '在做什么', '程序'].forEach(h => tr.appendChild(el('th', null, h)));
  thead.appendChild(tr); tbl.appendChild(thead);
  const tb = el('tbody');
  for (const r of recs) {
    const row = el('tr');
    const tdAv = el('td');
    tdAv.style.width = '42px';
    tdAv.appendChild(avatarEl(r.avatar, 'sm'));
    row.appendChild(tdAv);
    row.appendChild(el('td', 'time', fmtClock(r.ts)));
    const td2 = el('td', 'cat');
    const pill = el('span', 'pill ' + (r.on_task ? 'on' : 'off'), (r.on_task ? '在状态' : '分心') + ' · ' + (r.category || ''));
    td2.appendChild(pill);
    row.appendChild(td2);
    const td3 = el('td');
    td3.appendChild(document.createTextNode(r.activity || ''));
    if (r.basis) {
      const b = el('div', 'sub', '依据：' + r.basis);
      td3.appendChild(b);
    }
    row.appendChild(td3);
    row.appendChild(el('td', 'time', r.process || ''));
    tb.appendChild(row);
  }
  tbl.appendChild(tb);
}

// ---------- 控制面板 ----------
function renderControl(d) {
  const state = d.state || (d.running ? 'running' : 'stopped');
  const box = document.getElementById('cstate');
  const txt = document.getElementById('cstateText');
  const sub = document.getElementById('cstateSub');
  const btns = document.getElementById('cbtns');
  const note = document.getElementById('cnote');

  box.className = 'cstate ' + state;
  if (state === 'running') {
    txt.textContent = '监督中';
    sub.textContent = '每 ' + d.interval_sec + ' 秒截屏判定一次' +
      (d.pids && d.pids.length ? '（PID ' + d.pids.join(', ') + '）' : '');
  } else if (state === 'paused') {
    txt.textContent = '已暂停';
    sub.textContent = '进程还在待命，不会截图也不会花钱；点「继续监督」即可恢复';
  } else {
    txt.textContent = '未在监督';
    sub.textContent = '点「开始监督」就会在后台跑起来，关掉这个网页也不受影响';
  }

  btns.innerHTML = '';
  const mk = (label, cls, path, confirmText) => {
    const b = el('button', cls, label);
    b.disabled = busy;
    b.onclick = () => {
      if (confirmText && !window.confirm(confirmText)) return;
      doAction(path, b);
    };
    btns.appendChild(b);
    return b;
  };

  if (state === 'stopped') {
    mk('开始监督', 'primary', '/api/start');
  } else if (state === 'running') {
    mk('暂停判定', null, '/api/pause');
    mk('停止监督', 'danger', '/api/stop', '停止后本次监督结束，要重新开始请再点「开始监督」。确定停止？');
  } else {
    mk('继续监督', 'primary', '/api/resume');
    mk('停止监督', 'danger', '/api/stop', '停止后本次监督结束，要重新开始请再点「开始监督」。确定停止？');
  }
  mk('立即判一次', null, '/api/once');
  mk('导出 Markdown', null, '/api/export');

  // 设置入口就放在控制面板里
  const bCfg = el('button', null, '打开设置');
  bCfg.disabled = busy;
  bCfg.onclick = openDrawer;
  btns.appendChild(bCfg);

  note.innerHTML =
    '· 「暂停」只是不再判定，进程留着，恢复是瞬时的；「停止」是彻底结束监督进程。<br>' +
    '· 「立即判一次」会真的截屏并调用一次 API（约 $0.0006）。<br>' +
    '· 判定间隔、图片精度、学习目标、严格程度、提醒方式、<b>API 与模型</b>都在「打开设置」里改，不用碰配置文件。<br>' +
    '· 网页关掉不影响监督；桌面的 <code>学习监督</code> 快捷方式启动的是同一个东西。';
}

async function doAction(path, btn) {
  busy = true;
  const old = btn.textContent;
  btn.textContent = '处理中…';
  try {
    const r = await api(path, { method: 'POST' });
    const box = document.getElementById('ctlMsg');
    if (box) {
      box.textContent = (r.message || (r.ok ? '完成' : '失败')) + (r.activity ? ' → ' + r.activity : '');
      box.style.color = r.ok ? '#8fa6bf' : '#f2a65a';
    }
  } catch (e) {
    const box = document.getElementById('ctlMsg');
    if (box) { box.textContent = '请求失败：' + e.message; box.style.color = '#f2a65a'; }
  } finally {
    busy = false;
    btn.textContent = old;
    await refresh();
  }
}

// ---------- 设置抽屉 ----------
// 字段声明表：加一项设置只要在这里加一行。badge 决定显示"下一轮生效"还是"需重启"。
const CFG_GROUPS = [
  {
    title: '判定节奏', note: '下一轮判定起生效',
    fields: [
      { k: 'interval_sec', t: 'number', label: '判定间隔（秒）', hint: '每隔这么久截屏判定一次；越大越省', min: 10 },
      { k: 'idle_skip_sec', t: 'number', label: '空闲跳过阈值（秒）', hint: '超过这么久没有键鼠输入就不判定，也不计入统计' },
      { k: 'capture.min_gap_sec', t: 'number', label: '两次判定最小间隔（秒）', hint: '兜底闸门，防止重启后连着打好几次' },
      { k: 'capture.default_sec', t: 'number', label: '全局间隔覆盖（秒，留空=用上面的判定间隔）', hint: '按应用分配截图时，未命中任何规则的程序用哪个间隔' },
    ],
  },
  {
    title: '截屏与图片', 
    fields: [
      { k: 'detail', t: 'select', label: '图片精度', hot: true,
        options: [['low', 'low — 服务端缩到 512，最省'], ['high', 'high — 保留原分辨率，能看清小字'], ['auto', 'auto — 由服务端决定']] },
      { k: 'jpeg_quality', t: 'number', label: 'JPEG 质量（1-100）', hot: true, min: 1 },
      { k: 'max_width', t: 'number', label: '截图缩放宽度（像素）', restart: true, hint: '2K 屏用 1600 够看；调小更省 token' },
      { k: 'privacy.save_shots', t: 'bool', label: '把截图保存到磁盘', restart: true,
        hint: '关掉时截图只在内存里编码后直接发 API，不落盘（默认关）' },
      { k: 'privacy.shots_dir', t: 'text', label: '截图保存目录（相对项目根）', restart: true },
      { k: 'privacy.save_api_raw', t: 'bool', label: '保存模型原始回复', hot: true, hint: '便于事后排查误判' },
    ],
  },
  {
    title: '判定标准',
    fields: [
      { k: 'judge.goal', t: 'textarea', label: '学习目标', hot: true,
        hint: '写清楚你在准备什么，模型会照这个标准判断"算不算学习"' },
      { k: 'judge.strictness', t: 'select', label: '严格程度', hot: true,
        options: [['loose', 'loose — 宽松，获取知识信息就算学习'], ['normal', 'normal — 默认'],
                  ['strict', 'strict — 严格，只认做题/读教材/写代码/上课']] },
      { k: 'judge.extra_rules', t: 'list', label: '额外规则（每行一条）', hot: true,
        hint: '例如：在 Anki 里背单词算学习' },
      { k: 'judge.alias_rules', t: 'list', label: '归类约定（每行一条）', hot: true,
        hint: '例如：看技术博客算学习' },
    ],
  },
  {
    title: '提醒',
    fields: [
      { k: 'reminder.enabled', t: 'bool', label: '启用提醒', hot: true },
      { k: 'reminder.sound', t: 'bool', label: '提示音', hot: true },
      { k: 'reminder.mute_after_remind_sec', t: 'number', label: '提醒一次后安静多久（秒）', hot: true },
      { k: 'reminder.off_task_streak_required', t: 'number', label: '连续几次分心才提醒', hot: true, min: 1 },
      { k: 'reminder.auto_close_sec', t: 'number', label: '提醒窗自动关闭（秒，0=不自动关）', hot: true, min: 0 },
    ],
  },
  {
    title: 'API / 模型', note: '改这里要重启监督才生效',
    fields: [
      { k: 'api.base_url', t: 'text', label: '接口地址 base_url', restart: true,
        hint: '标准 OpenAI 兼容接口。注意有些服务商要带 /v1；代码会拼 /chat/completions' },
      { k: 'api.model', t: 'text', label: '模型名', restart: true, hint: '必须是支持图片输入的视觉模型' },
      { k: 'api.api_key_env', t: 'text', label: 'key 的环境变量名', restart: true, hint: '默认 DEEPSEEK_API_KEY' },
      { k: 'api.credentials_file', t: 'text', label: '凭据文件路径', restart: true,
        hint: '找不到环境变量时，从这个 yaml 里读 key（形如 refs: KEY: sk-xxx）' },
      { k: 'api.timeout_sec', t: 'number', label: '请求超时（秒）', restart: true },
      { k: 'api.max_tokens', t: 'number', label: '最大回复长度（token）', restart: true },
      { k: 'api.temperature', t: 'number', label: 'temperature', restart: true, step: '0.1',
        hint: '判定任务建议 0，输出更稳定' },
    ],
  },
];

let cfgCache = null;
let cfgDirty = false;

function openDrawer() {
  document.getElementById('drawer').classList.add('show');
  document.getElementById('backdrop').classList.add('show');
  loadConfig();
}
function closeDrawer() {
  if (cfgDirty && !window.confirm('有未保存的修改，确定关闭吗？')) return;
  document.getElementById('drawer').classList.remove('show');
  document.getElementById('backdrop').classList.remove('show');
  cfgDirty = false;
}

async function loadConfig() {
  const body = document.getElementById('cfgBody');
  body.innerHTML = '<div class="empty">读取配置中…</div>';
  try {
    cfgCache = await api('/api/config');
  } catch (e) {
    body.innerHTML = '';
    body.appendChild(el('div', 'empty', '读不到配置：' + e.message));
    return;
  }
  document.getElementById('cfgPath').textContent = cfgCache.config_path || '';
  renderConfigForm(cfgCache);
  setCfgMsg('');
  cfgDirty = false;
}

function setCfgMsg(text, color) {
  const m = document.getElementById('cfgMsg');
  m.textContent = text || '';
  m.style.color = color || 'var(--dim)';
}

function fieldNode(f, values) {
  const wrap = el('div', 'fld');
  const val = values[f.k];

  if (f.t === 'bool') {
    const lab = el('label', 'sw');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!val;
    input.dataset.key = f.k;
    input.dataset.type = 'bool';
    input.onchange = () => { cfgDirty = true; };
    lab.appendChild(input);
    lab.appendChild(el('span', null, f.label));
    wrap.appendChild(lab);
    if (f.hint) wrap.appendChild(el('div', 'hint', f.hint));
    return wrap;
  }

  const label = el('label');
  label.appendChild(document.createTextNode(f.label));
  if (f.restart) label.appendChild(el('span', 'badge', '需重启'));
  else if (f.hot) label.appendChild(el('span', 'badge hot', '下一轮生效'));
  wrap.appendChild(label);

  if (f.t === 'select') {
    const sel = document.createElement('select');
    sel.dataset.key = f.k;
    sel.dataset.type = 'str';
    for (const [v, text] of f.options) {
      const o = document.createElement('option');
      o.value = v; o.textContent = text;
      if (String(val) === v) o.selected = true;
      sel.appendChild(o);
    }
    sel.onchange = () => { cfgDirty = true; };
    wrap.appendChild(sel);
  } else if (f.t === 'textarea' || f.t === 'list') {
    const ta = document.createElement('textarea');
    ta.dataset.key = f.k;
    ta.dataset.type = f.t === 'list' ? 'list' : 'str';
    ta.value = f.t === 'list' ? (val || []).join('\n') : (val || '');
    ta.oninput = () => { cfgDirty = true; };
    wrap.appendChild(ta);
  } else {
    const input = document.createElement('input');
    input.type = f.t === 'number' ? 'number' : 'text';
    input.dataset.key = f.k;
    input.dataset.type = f.t === 'number' ? 'number' : 'str';
    if (f.min !== undefined) input.min = f.min;
    if (f.step) input.step = f.step;
    input.value = (val === null || val === undefined) ? '' : val;
    input.oninput = () => { cfgDirty = true; };
    wrap.appendChild(input);
  }
  if (f.hint) wrap.appendChild(el('div', 'hint', f.hint));
  return wrap;
}

function renderConfigForm(cfg) {
  const body = document.getElementById('cfgBody');
  body.innerHTML = '';
  const values = cfg.values || {};

  // API key 现状 + 新 key 输入
  const keySec = el('div', 'sec');
  const h = el('h4', null, 'API key');
  keySec.appendChild(h);
  const st = cfg.key || {};
  const line = el('div', 'keyline');
  const dot = el('div', 'dot2' + (st.ok ? '' : ' no'));
  line.appendChild(dot);
  line.appendChild(el('span', null, st.ok ? ('已配置：' + st.masked) : '未配置'));
  line.appendChild(el('span', 'src', st.source ? ('来源：' + st.source) : ''));
  keySec.appendChild(line);
  const keyFld = el('div', 'fld');
  keyFld.appendChild(el('label', null, '填写新的 key（留空表示不改）'));
  const keyInput = document.createElement('input');
  keyInput.type = 'password';
  keyInput.id = 'newApiKey';
  keyInput.placeholder = 'sk-...';
  keyInput.dataset.type = 'key';
  keyInput.oninput = () => { cfgDirty = true; };
  keyFld.appendChild(keyInput);
  const keyHint = el('div', 'hint',
    '保存后会写到 data/secrets.json（不进版本库）。优先级：环境变量 > 面板保存 > 凭据文件。');
  keyFld.appendChild(keyHint);
  keySec.appendChild(keyFld);
  body.appendChild(keySec);

  for (const g of CFG_GROUPS) {
    const sec = el('div', 'sec');
    const head = el('h4');
    head.appendChild(document.createTextNode(g.title));
    if (g.note) head.appendChild(el('span', 'tag', g.note));
    sec.appendChild(head);
    for (const f of g.fields) sec.appendChild(fieldNode(f, values));
    body.appendChild(sec);
  }

  // 截图策略只读提示（规则编辑留到后面单独做，这里先把现状说清楚）
  const ruleSec = el('div', 'sec');
  const rh = el('h4');
  rh.appendChild(document.createTextNode('截图策略'));
  rh.appendChild(el('span', 'tag', '按前台应用分配截图'));
  ruleSec.appendChild(rh);
  ruleSec.appendChild(el('div', 'hint',
    `当前生效 ${cfg.rules_count} 条规则（游戏不判定、短视频切换即查、聊天/阅读/编码各有节奏）。` +
    '规则的增删改暂时需要编辑 config.json 的 capture.rules —— 它是有序匹配的，做成表单容易搞乱优先级。'));
  body.appendChild(ruleSec);
}

function collectEdits() {
  const edits = {};
  document.querySelectorAll('#cfgBody [data-key]').forEach(node => {
    const key = node.dataset.key;
    const type = node.dataset.type;
    let v;
    if (type === 'bool') v = node.checked;
    else if (type === 'number') {
      v = node.value.trim() === '' ? null : Number(node.value);
      if (v !== null && !Number.isFinite(v)) v = node.value;   // 交给服务端报错
    } else if (type === 'list') {
      v = node.value.split('\n').map(s => s.trim()).filter(Boolean);
    } else v = node.value;

    // 和原值一致就不提交，避免无意义写入
    const orig = (cfgCache && cfgCache.values) ? cfgCache.values[key] : undefined;
    const same = (type === 'list')
      ? JSON.stringify(v) === JSON.stringify(orig || [])
      : (v === orig || (v === null && (orig === null || orig === undefined)));
    if (!same) edits[key] = v;
  });
  return edits;
}

async function saveConfig() {
  const edits = collectEdits();
  const keyEl = document.getElementById('newApiKey');
  const newKey = keyEl ? keyEl.value.trim() : '';
  if (!Object.keys(edits).length && !newKey) {
    setCfgMsg('没有改动。');
    return;
  }
  const btn = document.getElementById('btnSaveCfg');
  btn.disabled = true;
  btn.textContent = '保存中…';
  setCfgMsg('正在保存…');
  try {
    const r = await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ edits, api_key: newKey || null }),
    });
    if (r.ok) {
      if (keyEl) keyEl.value = '';
      cfgDirty = false;
      setCfgMsg(r.message, '#4cc97a');
      await loadConfig();          // 重新读一遍，反映真实落盘结果
      setCfgMsg(r.message, '#4cc97a');
      refresh();                   // 状态区也可能受影响
    } else {
      setCfgMsg(r.message || '保存失败', '#f2a65a');
    }
  } catch (e) {
    setCfgMsg('保存请求失败：' + e.message, '#f2a65a');
  } finally {
    btn.disabled = false;
    btn.textContent = '保存设置';
  }
}

async function testApi() {
  const btn = document.getElementById('btnTestApi');
  const keyEl = document.getElementById('newApiKey');
  btn.disabled = true;
  btn.textContent = '测试中…';
  setCfgMsg('正在用一张内置小图测试（不截屏、不读你的屏幕）…');
  try {
    const edits = collectEdits();
    const useEdits = {};
    for (const k of ['api.base_url', 'api.model', 'api.api_key_env']) {
      if (k in edits) useEdits[k] = edits[k];
    }
    const r = await api('/api/check-api', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ edits: useEdits, api_key: (keyEl && keyEl.value.trim()) || null }),
    });
    if (r.ok) {
      setCfgMsg(r.message + (r.seen ? ('；模型看到：' + r.seen) : ''), '#4cc97a');
    } else {
      setCfgMsg('连通失败：' + r.message, '#f2a65a');
    }
  } catch (e) {
    setCfgMsg('测试请求失败：' + e.message, '#f2a65a');
  } finally {
    btn.disabled = false;
    btn.textContent = '测试 API 连通';
  }
}

document.getElementById('btnCloseDrawer').onclick = closeDrawer;
document.getElementById('backdrop').onclick = closeDrawer;
document.getElementById('btnSaveCfg').onclick = saveConfig;
document.getElementById('btnTestApi').onclick = testApi;
document.getElementById('btnReloadCfg').onclick = () => {
  cfgDirty = false;
  loadConfig();
};
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeDrawer();
});

// 角色头像：提醒用的那批素材（assets/reminder/face/*.png）在这里复用。
// 名字同时充当 alt 与提示，鼠标悬停能知道这张脸代表什么。
const AVATAR_LABEL = {
  general: ['开小差', '通用：又走神了'],
  shortvideo: ['刷视频', '短视频/推荐流'],
  gaming: ['打游戏', '游戏'],
  social: ['聊天', '社交软件'],
  sleepy: ['发呆', '闲置/犯困'],
  thumbsup: ['回来啦', '刚从不专注切回专注'],
  relax: ['休息', '计划的休息时段'],
  celebrate: ['完成', '计划完成'],
};

function avatarEl(key, size) {
  const k = AVATAR_LABEL[key] ? key : 'general';
  const img = document.createElement('img');
  img.className = 'av ' + (size || 'sm');
  img.src = '/avatars/' + k + '.png';
  img.alt = AVATAR_LABEL[k][0];
  img.title = AVATAR_LABEL[k][1];
  // 不加 loading="lazy"：这些都是 30-60px 的小图，且同一页面里重复引用同一张，
  // 浏览器天然只下载一次。懒加载反而会让视口外的头像长时间空着。
  return img;
}

// ---------- Live2D 桌宠 ----------
// 跟着判定状态换表情。模型是 CC BY-NC-SA 4.0（见仓库 NOTICE.md），
// 渲染靠 assets/vendor 下的 Cubism Core + pixi + pixi-live2d-display。
//
// 表情 id 来自 tools/build_live2d_model.py 的 EXPRESSIONS 表。
// 找不到 PIXI（离线、vendor 缺失）时不报错，只显示一行说明 ——
// 桌宠是锦上添花，坏掉不该影响仪表盘的主功能。
const PET_EXPR = {
  onTask: 'star', comeback: 'sweat', offGeneral: 'tease', offShort: 'tongue',
  offGame: 'angry', offSocial: 'tease', idle: 'blank', sleepy: 'sleepy',
  breakTime: 'heart', done: 'excited', bad: 'cry', night: 'dark',
};
const PET_TEXT = {
  star: '在状态，看着挺像样的。',
  sweat: '刚才还在别处，现在回来了——这就对了。',
  tease: '哎呀呀，又在开小差呢。',
  tongue: '再刷一个就学习？你上一个「再刷一个」是二十分钟前说的。',
  angry: '这局不算，那下一局呢。存档不会跑，作业会。',
  blank: '盯着屏幕发呆不算学习，也不算休息。',
  sleepy: '困了就别硬撑，起身走两步。',
  heart: '这轮结束了，去休息。',
  excited: '计划完成，干得漂亮。',
  cry: '连续好几次了。要不要先休息一下？',
  dark: '夜深了，早点睡比多熬一小时有用。',
  dizzy: '我眼睛都转晕了，你也歇会儿吧。',
  question: '这条我有点拿不准，你自己看看。',
  blush: '行吧，这次算你厉害。',
  normal: '',
};

let petApp = null;
let petModel = null;
let petExprNow = '';
let petFailed = false;

function petSetExpr(id, force) {
  if (!petModel || petFailed) return;
  const key = PET_EXPR[id] || id;
  if (!force && key === petExprNow) return;
  const em = petModel.internalModel
    && petModel.internalModel.motionManager
    && petModel.internalModel.motionManager.expressionManager;
  if (!em) return;
  try {
    em.setExpression(key);
    petExprNow = key;
    const say = document.getElementById('petSay');
    if (say) say.textContent = PET_TEXT[key] || PET_TEXT.normal || '';
    const tag = document.getElementById('petTag');
    if (tag) tag.textContent = key;
  } catch (e) {
    // 某个表情缺失不该让桌宠停摆
    petExprNow = '';
  }
}

function petMotion(name) {
  if (!petModel || petFailed) return;
  try { petModel.motion(name); } catch (e) { /* 动作缺失就跳过 */ }
}

async function initPet() {
  const canvas = document.getElementById('pet');
  if (!canvas) return;
  const tag = document.getElementById('petTag');
  const say = document.getElementById('petSay');
  const note = document.getElementById('petNote');
  if (typeof PIXI === 'undefined' || !PIXI.live2d) {
    petFailed = true;
    if (tag) tag.textContent = '不可用';
    if (say) say.textContent = '没有加载到 Live2D 运行时（assets/vendor 可能缺失）。';
    return;
  }
  try {
    const rect = canvas.parentElement.getBoundingClientRect();
    const W = Math.max(200, Math.round(rect.width || 300));
    const H = 300;
    petApp = new PIXI.Application({
      view: canvas, width: W, height: H, backgroundAlpha: 0,
      antialias: true, autoStart: true, resolution: window.devicePixelRatio || 1,
      autoDensity: true,
      // 帧率上限。Live2D 的呼吸/眨眼在 20fps 下完全看不出差别，但 CPU 能省一半：
      // 实测 60fps 时桌宠约占 0.45 个核，这是本项目里最"贵"的一处。
      // 需要更高帧率的场合（鼠标跟随）也够用。
      maxFPS: 20,
    });
    // 标签页切到后台时停掉渲染。页面不可见时浏览器本来就不合成这一帧，
    // 但 PIXI 的 ticker 仍在跑模型与物理演算，纯属白烧 CPU。
    document.addEventListener('visibilitychange', () => {
      if (!petApp || petFailed) return;
      const t = PIXI.Ticker.shared;
      if (document.hidden) t.stop();
      else { t.maxFPS = 20; t.start(); }
    });
    petModel = await PIXI.live2d.Live2DModel.from('/live2d/c_0120.model3.json',
                                                  {autoInteract: true, autoUpdate: true});
    petApp.stage.addChild(petModel);
    const sc = Math.min(W / petModel.width, H / petModel.height) * 1.06;
    petModel.scale.set(sc);
    petModel.anchor.set(0.5, 0.5);
    petModel.position.set(W / 2, H / 2 + 6);
    if (tag) tag.textContent = '就绪';
    if (note) note.textContent = '';
    petSetExpr('star', true);
    petMotion('idle');
    // 点一下会有反应
    canvas.style.cursor = 'pointer';
    canvas.onclick = () => {
      petMotion('bubble');
      const say2 = document.getElementById('petSay');
      if (say2) say2.textContent = '别戳我，去学习（我还是要陪你一会儿的）。';
    };
    return true;
  } catch (e) {
    petFailed = true;
    if (tag) tag.textContent = '加载失败';
    if (say) say.textContent = '模型没加载起来：' + (e && e.message ? e.message : e);
    return false;
  }
}

// 按最新一条判定决定表情。规则与 lib/avatars.py 保持一致：
// 只有"刚从不专注切回专注"才给鼓励，一直专注就用常态表情（否则像刷屏）。
function petSyncFromData(d) {
  if (!petModel || petFailed) return;
  const t = (d && d.today) || {};
  const last = t.last;
  if (!last) { petSetExpr('blank'); return; }
  const p = (d && d.plan) || {};
  if (p.finished) { petSetExpr('done'); return; }
  if (p.active && p.is_break) { petSetExpr('breakTime'); return; }

  const recs = t.recent || [];
  const prev = recs.length >= 2 ? recs[recs.length - 2] : null;
  const avatar = last.avatar;
  if (avatar === 'thumbsup') petSetExpr('sweat');
  else if (avatar === 'celebrate') petSetExpr('done');
  else if (avatar === 'relax') petSetExpr('breakTime');
  else if (avatar === 'shortvideo') petSetExpr('offShort');
  else if (avatar === 'gaming') petSetExpr('offGame');
  else if (avatar === 'social') petSetExpr('offSocial');
  else if (avatar === 'sleepy') petSetExpr('sleepy');
  else if (avatar === 'general') {
    petSetExpr(last.on_task ? 'star' : 'offGeneral');
  } else petSetExpr('star');

  // 时间轴上最近几条连续分心 -> 升级成"哭"，但只在真的连续时
  if (!last.on_task && recs.length >= 3) {
    const tail = recs.slice(-3);
    if (tail.every(r => r && !r.on_task)) petMotion('splash');
  }
}

// 倒计时在本地按绝对时间戳算，每秒只更新数字与圆环；不重建卡片，
// 否则正在填的输入框会失焦、按钮会跳。
let pomoData = null;        // 服务端给的 plan 描述
let pomoPresets = [];       // 预设列表
let pomoSetup = { preset: 'pomodoro', rounds: 0, note: '', remind_on_break: false, strict_break: false };
let pomoBusy = false;

function fmtCountdown(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
}

function pomoMsg(text, color) {
  const box = document.getElementById('ctlMsg');
  if (box) { box.textContent = text || ''; box.style.color = color || 'var(--dim)'; }
}

// 把用户调好的数值存进 config.json —— 自定义一次，以后打开就还是你的节奏。
// 没这一步的话，自定义只在浏览器内存里，刷新就回到 25/5。
let pomoSaveTimer = null;
function pomoSaveSoon() {
  clearTimeout(pomoSaveTimer);
  pomoSaveTimer = setTimeout(async () => {
    try {
      await api('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          edits: {
            'plan.preset': pomoSetup.preset,
            'plan.focus_min': pomoSetup.focus_min || 25,
            'plan.break_min': pomoSetup.break_min || 5,
            'plan.long_every': pomoSetup.long_every || 0,
            'plan.long_break_min': pomoSetup.long_break_min || 0,
            'plan.rounds': pomoSetup.rounds || 0,
            'plan.remind_on_break': !!pomoSetup.remind_on_break,
            'plan.strict_break': !!pomoSetup.strict_break,
            'plan.start_monitor': pomoSetup.start_monitor !== false,
          },
        }),
      });
      pomoMsg('已记住你的节奏（下次打开还是这个）', '#4cc97a');
    } catch (e) {
      pomoMsg('节奏没能保存：' + e.message, '#f2a65a');
    }
  }, 700);
}

// 用配置里的 plan.* 初始化表单（只做一次）
async function pomoLoadSaved() {
  try {
    const c = await api('/api/config');
    const v = c.values || {};
    const saved = {
      preset: v['plan.preset'] || 'pomodoro',
      focus_min: v['plan.focus_min'],
      break_min: v['plan.break_min'],
      long_every: v['plan.long_every'],
      long_break_min: v['plan.long_break_min'],
      rounds: v['plan.rounds'] || 0,
      remind_on_break: !!v['plan.remind_on_break'],
      strict_break: !!v['plan.strict_break'],
      // 没存过时按 true（默认联动）；存过 false 就尊重用户的选择
      start_monitor: v['plan.start_monitor'] !== false,
    };
    pomoSetup = Object.assign({ note: pomoSetup.note || '' }, saved);
    renderPomo(null);
  } catch (e) {
    /* 读不到就用内置默认，不影响使用 */
  }
}

function renderPomo(d) {
  if (d) {
    pomoData = d.plan || { active: false };
    if (Array.isArray(d.plan_presets) && d.plan_presets.length) pomoPresets = d.plan_presets;
  }
  const host = document.getElementById('pomo');
  const tag = document.getElementById('pomoTag');
  if (!host) return;
  host.innerHTML = '';

  const p = pomoData || { active: false };
  const wrap = el('div', 'pomo' + (p.active && p.is_break ? ' rest' : ''));

  if (p.active) {
    // ---- 运行中：圆环倒计时 ----
    const total = Math.max(1, p.phase_sec);
    const remain = Math.max(0, p.phase_ends_at - Date.now() / 1000);
    const ratio = Math.max(0, Math.min(1, remain / total));
    const R = 50, C = 2 * Math.PI * R;

    const ring = el('div', 'ring');
    const svg = svgEl('svg', { width: 118, height: 118, viewBox: '0 0 118 118' });
    svg.appendChild(svgEl('circle', {
      cx: 59, cy: 59, r: R, fill: 'none', stroke: '#22303f', 'stroke-width': 9 }));
    svg.appendChild(svgEl('circle', {
      cx: 59, cy: 59, r: R, fill: 'none',
      stroke: p.is_break ? '#4cc97a' : '#ffd166',
      'stroke-width': 9, 'stroke-linecap': 'round',
      'stroke-dasharray': C, 'stroke-dashoffset': C * (1 - ratio),
      transform: 'rotate(-90 59 59)' }));
    ring.appendChild(svg);
    const box = el('div', 'txt');
    const big = el('div', 'big', fmtCountdown(remain));
    big.id = 'pomoClock';
    box.appendChild(big);
    box.appendChild(el('div', 'sub', p.is_break ? '休息中' : '专注中'));
    ring.appendChild(box);
    wrap.appendChild(ring);

    const info = el('div', 'info');
    const ph = el('div', 'phase', p.phase_label);
    ph.appendChild(el('span', 'rd',
      (p.target_rounds ? `第 ${p.round} / ${p.target_rounds} 轮` : `第 ${p.round} 轮`)
      + `｜${p.focus_min} 分专注 / ${p.break_min} 分休息`));
    info.appendChild(ph);
    if (p.note) info.appendChild(el('div', 'goal', '主题：' + p.note));

    const chain = el('div', 'chain');
    const shown = Math.max(p.target_rounds || 0, p.round, 1);
    for (let i = 1; i <= Math.min(shown, 16); i++) {
      const dot = el('i');
      if (i < p.round) dot.className = 'done';
      else if (i === p.round) dot.className = p.is_break ? 'rest' : 'now';
      chain.appendChild(dot);
    }
    const doneTxt = `已完成 ${p.done_focus_rounds} 轮专注`
      + (p.rounds_total_sec ? `（${fmtDur(p.rounds_total_sec)}）` : '');
    chain.appendChild(el('span', 'sub', doneTxt));
    info.appendChild(chain);

    const acts = el('div', 'acts');
    const bSkip = el('button', null, p.is_break ? '休息够了，继续' : '提前休息');
    bSkip.onclick = () => pomoAction({ action: 'skip' });
    bSkip.disabled = pomoBusy;
    acts.appendChild(bSkip);
    const bStop = el('button', 'danger', '结束计划');
    bStop.onclick = () => pomoAction({ action: 'stop' });
    bStop.disabled = pomoBusy;
    acts.appendChild(bStop);
    info.appendChild(acts);

    if (p.basis) info.appendChild(el('div', 'basis', '节奏依据：' + p.basis));
    wrap.appendChild(info);
    if (tag) tag.textContent = `${p.preset_label}｜${p.phase_label}`;
  } else {
    // ---- 未开始 / 上次已结束：设置表单 ----
    const setup = el('div', 'setup');
    const presets = el('div', 'presets');
    for (const pr of pomoPresets) {
      const b = el('button', pomoSetup.preset === pr.key ? 'on' : null, pr.label);
      b.title = pr.basis || '';
      b.onclick = () => {
        pomoSetup.preset = pr.key;
        // 选预设 = 套用它的数值；但「自定义」不该抹掉你已经调好的数字
        // （之前这里把自定义重置成 25/5，等于"点自定义反而丢掉自定义"）
        if (pr.key !== 'custom') {
          pomoSetup.focus_min = pr.focus_min;
          pomoSetup.break_min = pr.break_min;
          pomoSetup.long_every = pr.long_every;
          pomoSetup.long_break_min = pr.long_break_min;
          pomoSaveSoon();
        }
        renderPomo(null);
      };
      presets.appendChild(b);
    }
    setup.appendChild(presets);

    const cur = pomoPresets.find(x => x.key === pomoSetup.preset) || pomoPresets[0] || {};
    if (pomoSetup.focus_min === undefined) {
      pomoSetup.focus_min = cur.focus_min || 25;
      pomoSetup.break_min = cur.break_min || 5;
      pomoSetup.long_every = cur.long_every || 0;
      pomoSetup.long_break_min = cur.long_break_min || 0;
    }

    const row1 = el('div', 'row');
    const mkNum = (label, key) => {
      row1.appendChild(el('span', null, label));
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.min = 0;
      inp.value = pomoSetup[key];
      inp.onchange = () => {
        pomoSetup[key] = Math.max(0, Number(inp.value) || 0);
        pomoSetup.preset = 'custom';       // 手改数值就等于自定义
        pomoSaveSoon();
        renderPomo(null);
      };
      row1.appendChild(inp);
    };
    mkNum('专注', 'focus_min');
    mkNum('分钟／休息', 'break_min');
    mkNum('分钟｜每', 'long_every');
    mkNum('轮长休', 'long_break_min');
    row1.appendChild(el('span', null, '分钟'));
    setup.appendChild(row1);

    const row2 = el('div', 'row');
    row2.appendChild(el('span', null, '做几轮'));
    const rInp = document.createElement('input');
    rInp.type = 'number'; rInp.min = 0; rInp.value = pomoSetup.rounds || 0;
    rInp.title = '0 表示不限轮数，做到你手动停';
    rInp.onchange = () => {
      pomoSetup.rounds = Math.max(0, Number(rInp.value) || 0);
      pomoSaveSoon();
    };
    row2.appendChild(rInp);
    row2.appendChild(el('span', null, '（0 = 不限）｜主题'));
    const nInp = document.createElement('input');
    nInp.type = 'text';
    nInp.placeholder = '比如：高数第三章习题';
    nInp.value = pomoSetup.note || '';
    nInp.oninput = () => { pomoSetup.note = nInp.value; };
    row2.appendChild(nInp);
    setup.appendChild(row2);

    const row3 = el('div', 'row');
    // parent 必须做成参数：mkSw 是闭包，若在函数体里写死 row3.appendChild，
    // 后面想放到别的行就会全部堆进 row3（踩过一次）
    const mkSw = (parent, label, key, title) => {
      const lab = el('label', 'sw2');
      const inp = document.createElement('input');
      inp.type = 'checkbox';
      inp.checked = !!pomoSetup[key];
      inp.onchange = () => { pomoSetup[key] = inp.checked; pomoSaveSoon(); };
      lab.appendChild(inp);
      lab.appendChild(el('span', null, label));
      lab.title = title || '';
      parent.appendChild(lab);
    };
    mkSw(row3, '休息时也提醒分心', 'remind_on_break',
      '默认关：休息就该离开屏幕，这时候弹提醒反而让人不敢休息');
    mkSw(row3, '把休息计入统计', 'strict_break',
      '默认关：休息时的判定不计入专注率，避免"老实休息反而数据难看"');
    setup.appendChild(row3);

    // 单独一行放这个开关：它决定这一轮有没有统计，比另外两个更需要被看见
    const row4 = el('div', 'row');
    mkSw(row4, '同时启动监督', 'start_monitor',
      '默认勾选：开始专注时一起把监督起来，这一轮才会有判定与统计。'
      + '取消勾选则只计时，不截图、不调用 API。');
    setup.appendChild(row4);

    const acts = el('div', 'acts');
    const bStart = el('button', 'primary', '开始专注');
    bStart.onclick = () => pomoAction(Object.assign({ action: 'start' }, pomoSetup));
    bStart.disabled = pomoBusy;
    acts.appendChild(bStart);
    if (p.finished) {
      const bClear = el('button', null, '清除上次记录');
      bClear.onclick = () => pomoAction({ action: 'clear' });
      acts.appendChild(bClear);
    }
    setup.appendChild(acts);

    if (p.finished && p.stop_reason) {
      setup.appendChild(el('div', 'basis',
        `上一次：${p.preset_label || ''}｜完成 ${p.done_focus_rounds || 0} 轮专注｜${p.stop_reason}`));
    } else if (cur.basis) {
      setup.appendChild(el('div', 'basis', '节奏依据：' + cur.basis));
    }
    wrap.appendChild(setup);
    if (tag) tag.textContent = p.finished ? '上次已结束' : '';
  }

  host.appendChild(wrap);
}

async function pomoAction(body) {
  pomoBusy = true;
  try {
    const r = await api('/api/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (r.plan) pomoData = r.plan;
    pomoMsg(r.message || (r.ok ? '完成' : '失败'), r.ok === false ? '#f2a65a' : '#4cc97a');
    renderPomo(null);
    refresh();
  } catch (e) {
    pomoMsg('操作失败：' + e.message, '#f2a65a');
  } finally {
    pomoBusy = false;
  }
}

// 每秒只改数字与圆环进度
function tickPomo() {
  const p = pomoData;
  if (!p || !p.active) return;
  const remain = Math.max(0, p.phase_ends_at - Date.now() / 1000);
  const clock = document.getElementById('pomoClock');
  if (clock) clock.textContent = fmtCountdown(remain);
  const arc = document.querySelector('#pomo .ring svg circle[stroke-dasharray]');
  if (arc) {
    const C = 2 * Math.PI * 50;
    const total = Math.max(1, p.phase_sec);
    arc.setAttribute('stroke-dashoffset', C * (1 - Math.max(0, Math.min(1, remain / total))));
  }
  // 到点了：先本地收起，再让下一次轮询取回新阶段
  if (remain <= 0 && !pomoBusy) {
    p.active = false;
    refresh();
  }
}

// ---------- 主循环 ----------
let timer = null;
let offlineNotified = false;

function showOffline() {
  // 页面还开着但服务没了（服务进程退出、被回收、机器重启过）：要说人话，而不是 Failed to fetch
  const dot = document.getElementById('dot');
  const txt = document.getElementById('statusText');
  if (dot) dot.className = 'dot off';
  if (txt) txt.textContent = '仪表盘服务已断开';

  const box = document.getElementById('warnBox');
  if (box && !offlineNotified) {
    box.innerHTML = '';
    const w = el('div', 'warn');
    w.innerHTML = '连不上仪表盘服务了——页面还开着，但后台服务已经退出。<br>' +
      '解决办法：双击桌面上的 <b>「学习监督 仪表盘」</b> 快捷方式重新启动服务，然后刷新本页。<br>' +
      '<span style="color:#8fa6bf">（服务退出一般是因为重启/注销，或它的窗口被关掉了。' +
      '监督进程如果还在跑，重启服务后数据会自动接上。）</span>';
    box.appendChild(w);
    offlineNotified = true;
  }

  const stateText = document.getElementById('cstateText');
  const sub = document.getElementById('cstateSub');
  const btns = document.getElementById('cbtns');
  if (stateText) stateText.textContent = '服务未运行';
  if (sub) sub.textContent = '按钮暂时不可用，先启动仪表盘服务';
  if (btns) btns.innerHTML = '';
}

// 非今天时，在标题和"现在"面板上标明日期，避免误读成实时数据
function tlApplyDateLabels(d) {
  const st = document.querySelector('#statusText');
  const nowH2 = document.querySelector('#nowCard h2');
  const day = d && d.view_day;
  const past = d && d.is_today === false;
  if (nowH2) {
    nowH2.innerHTML = past
      ? '当天最后一条 <span class="tag">' + day + '（历史）</span>'
      : '现在';
  }
  document.body.classList.toggle('past-day', !!past);
}

async function refresh() {
  try {
    const d = await api('/api/data' + (tlDay ? ('?day=' + encodeURIComponent(tlDay)) : ''));
    tlBuildDays(d);
    if (offlineNotified) {
      offlineNotified = false;
      document.getElementById('warnBox').innerHTML = '';
    }
    renderStatus(d);
    renderWarn(d);
    renderCards(d);
    renderTimeline(d);
    renderOffList(d);
    renderDonut(d);
    renderWeek(d);
    renderProcs(d);
    renderMeta(d);
    renderRecent(d);
    renderControl(d);
    renderPomo(d);
    petSyncFromData(d);
    // 必须放在 renderCards 之后：它每次都会重建卡片，把"现在"这个标题覆盖回去
    tlApplyDateLabels(d);
  } catch (e) {
    showOffline();
  }
}

// 支持用 ?day=YYYY-MM-DD 直接打开某一天（可收藏 / 分享链接）
(function initDayFromUrl() {
  const m = /[?&]day=(\d{4}-\d{2}-\d{2})/.exec(location.search);
  if (m) {
    tlDay = m[1];
    const todayStr = new Date().toLocaleDateString('sv-SE');
    if (tlDay === todayStr) tlDay = null;      // 就是今天的话不必固定住
  }
})();

document.getElementById('btnRefresh').onclick = refresh;

// 时间轴工具条：预设 / 自定义区间 / 重置 / 明细跟随
tlBuildPresets();
document.getElementById('tlApply').onclick = tlApplyCustom;
document.getElementById('tlReset').onclick = () => {
  tlRange = null;
  syncTlInputs();
  tlMarkPreset(null);
  clearTlWarn();
  renderTimeline(null);
};
for (const id of ['tlFrom', 'tlTo']) {
  const node = document.getElementById(id);
  node.addEventListener('keydown', e => { if (e.key === 'Enter') tlApplyCustom(); });
}
document.getElementById('offFollow').onchange = () => renderTimeline(null);

refresh();
timer = setInterval(refresh, 5000);
// 桌宠是异步加载模型（几百毫秒），不阻塞首屏。加载好后 refresh 会同步表情。
initPet().then(ok => { if (ok) refresh(); });
// 倒计时单独每秒走：5 秒轮询会让秒数一跳一跳
setInterval(tickPomo, 1000);
// 读回上次保存的节奏（自定义数值存在 config.json 里，不是浏览器内存）
pomoLoadSaved();

// 支持用 #settings 直接打开设置（方便收藏成"设置页"）
if (location.hash === '#settings' || location.search.indexOf('settings=1') >= 0) {
  openDrawer();
}

// 窗口尺寸变化后重新测量（时间轴/周图按容器实际宽度绘制）
let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(refresh, 250);
});
