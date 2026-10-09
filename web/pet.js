'use strict';
// 独立桌宠窗口的前端。与仪表盘里的桌宠共用模型与判断规则，
// 但只拉轻量接口 /api/pet，不拉整天数据。
//
// 互动：
//   · 拖顶栏移动窗口（靠 CSS 的 -webkit-app-region:drag）
//   · 点角色：摸摸头 -> 播动作 + 说一句话
//   · 双击角色：催一句（把它当前状态说出来）
//   · 悬停：表情变柔和（回正）
//   · 顶栏按钮：静音 / 收起 / 关闭

const PET_EXPR = {
  onTask: 'star', comeback: 'sweat', offGeneral: 'tease', offShort: 'tongue',
  offGame: 'angry', offSocial: 'tease', idle: 'blank', sleepy: 'sleepy',
  breakTime: 'heart', done: 'excited',
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
};

const PET_CARD_LABEL = {
  general: '分心', shortvideo: '刷视频', gaming: '游戏', social: '聊天',
  sleepy: '发呆', thumbsup: '回来啦', relax: '休息', celebrate: '完成',
};

let app = null;
let model = null;
let exprNow = '';
let failed = false;
let muted = false;
let lastSeq = 0;
let bubbleUntil = 0;      // 这段时间内气泡显示"刚发生的事"，不显示倒计时
let plan = null;
let cfg = {max_fps: 20, show_plan: true, speak: true, pause_when_hidden: true};

const $ = id => document.getElementById(id);

function setExpr(id, force) {
  if (!model || failed) return '';
  const key = PET_EXPR[id] || id;
  if (!force && key === exprNow) return key;
  const em = model.internalModel
    && model.internalModel.motionManager
    && model.internalModel.motionManager.expressionManager;
  if (!em) return key;
  try { em.setExpression(key); exprNow = key; } catch (e) { exprNow = ''; }
  return key;
}

function say(text, holdMs) {
  const el = $('say');
  if (!el || !text) return;
  el.textContent = text;
  if (holdMs) bubbleUntil = Date.now() + holdMs;
}

function motion(name) {
  if (!model || failed) return;
  try { model.motion(name); } catch (e) { /* 动作缺失就跳过 */ }
}

// 点一下：摸摸头
function onPoke() {
  motion('bubble');
  setExpr('heart', true);
  say('别戳我…好吧，摸一下也行。', 6000);
  setTimeout(() => { exprNow = ''; }, 6500);
}

// 双击：催一句当前状态
function onNudge() {
  if (plan && plan.active) {
    const s = Math.max(0, Number(plan.remaining_sec) || 0);
    const clock = String(Math.floor(s / 60)).padStart(2, '0') + ':' +
                  String(s % 60).padStart(2, '0');
    motion(plan.is_break ? 'openLid' : 'selfie');
    say(plan.is_break
      ? `休息还有 ${clock}，去倒杯水吧。`
      : `还有 ${clock}，我盯着你呢。`, 8000);
  } else {
    motion('ketchup');
    say('现在没在计时。想学就点「开始专注」，我陪你。', 8000);
  }
}

async function boot() {
  const params = new URLSearchParams(location.search);
  const style = params.get('style') || 'solid';
  document.body.classList.add(style);

  const bar = $('bar');
  if (bar) {
    // app 模式下 CSS 拖动区足够；这里再补一个"双击标题栏复位到右上角"
    bar.addEventListener('dblclick', () => {
      say('双击顶栏可以试着把窗口挪到自己喜欢的位置。', 4000);
    });
  }
  $('bClose').onclick = async () => {
    say('那我先下去啦，下次见。', 1200);
    setTimeout(() => { try { window.close(); } catch (e) {} }, 900);
  };
  $('bHide').onclick = () => {
    document.getElementById('root').style.visibility = 'hidden';
    setTimeout(() => { document.getElementById('root').style.visibility = ''; }, 2500);
    say('（我躲两秒就回来）', 2400);
  };
  $('bMute').onclick = async () => {
    muted = !muted;
    $('bMute').style.color = muted ? '#f2a65a' : '';
    $('bMute').textContent = muted ? '♪̸' : '♪';
    say(muted ? '好，我安静。' : '可以出声了。', 3000);
  };

  if (typeof PIXI === 'undefined' || !PIXI.live2d) {
    failed = true;
    say('没有加载到 Live2D 运行时（assets/vendor 可能缺失）。');
    return;
  }

  try {
    const raw = await (await fetch('/api/pet')).json();
    Object.assign(cfg, {
      enabled: raw['pet.enabled'] !== false,
      max_fps: Number(raw['pet.max_fps']) || 20,
      show_plan: raw['pet.show_plan'] !== false,
      speak: raw['pet.speak'] !== false,
      pause_when_hidden: raw['pet.pause_when_hidden'] !== false,
    });
  } catch (e) { /* 用默认值 */ }
  if (!cfg.enabled) {
    failed = true;
    say('桌宠在设置里被关掉了。打开仪表盘 → 设置 → 桌宠，勾上「启用」即可。');
    return;
  }

  const canvas = $('pet');
  // 等一帧再量：boot() 是脚本一加载就调的，那时 flex 布局可能还没完成，
  // 量到的父容器尺寸是过期的，模型会画偏或被裁掉（实测踩过）。
  await new Promise(r => requestAnimationFrame(() => r()));
  const box = canvas.parentElement.getBoundingClientRect();
  const W = Math.max(160, Math.round(box.width));
  const H = Math.max(160, Math.round(box.height));
  app = new PIXI.Application({
    view: canvas, width: W, height: H, backgroundAlpha: true,
    antialias: true, autoStart: true, resolution: window.devicePixelRatio || 1,
    autoDensity: true, maxFPS: cfg.max_fps,
  });
  try {
    PIXI.Ticker.shared.maxFPS = cfg.max_fps;
    if (app.ticker) app.ticker.maxFPS = cfg.max_fps;
  } catch (e) { /* 忽略 */ }

  try {
    model = await PIXI.live2d.Live2DModel.from('/live2d/c_0120.model3.json',
                                               {autoInteract: true, autoUpdate: true});
  } catch (e) {
    failed = true;
    say('模型没加载起来：' + (e && e.message ? e.message : e));
    return;
  }
  app.stage.addChild(model);

  // 填满并居中。
  //
  // 缩放为什么这么算（踩了一串坑，写清楚）：
  //   · model.width/height 是 4068×4068（模型画布尺寸），除以它才对。
  //     但实测某些时序下 model.width 会读到非预期值，导致算出 sc=1 ——
  //     角色被放成几百倍，画面里只剩脸部皮肤。
  //   · 所以这里不信单一来源：**用 getBounds() 实测模型当前占多大**，
  //     再按比例反推需要的缩放。这个值是渲染器自己算的，最可靠。
  //   · 舞台尺寸用逻辑像素（getBoundingClientRect），PIXI 自己乘 resolution。
  function fit() {
    const b = canvas.getBoundingClientRect();
    const w = Math.max(80, Math.round(b.width) || 200);
    const h = Math.max(80, Math.round(b.height) || 200);
    const curW = app.renderer.width / app.renderer.resolution;
    const curH = app.renderer.height / app.renderer.resolution;
    if (Math.abs(curW - w) > 1 || Math.abs(curH - h) > 1) {
      app.renderer.resize(w, h);
    }
    model.anchor.set(0.5, 0.5);
    model.position.set(0, 0);
    model.scale.set(1);
    // 先把缩放归 1，量出模型"原尺寸"占多少，再算目标缩放
    let bw = 0, bh = 0;
    try {
      const bounds = model.getBounds();
      bw = bounds.width;
      bh = bounds.height;
    } catch (e) { /* 落回下面的兜底 */ }
    if (!(bw > 0) || !(bh > 0)) {
      bw = model.width || 1;
      bh = model.height || 1;
    }
    const sc = Math.min(w / bw, h / bh) * 0.98;
    model.scale.set(sc);
    model.position.set(w / 2, h / 2);
    window.__petFit = {
      w, h, dpr: window.devicePixelRatio || 1, sc: +sc.toFixed(5),
      modelWH: [model.width, model.height], bounds: [Math.round(bw), Math.round(bh)],
      rw: app.renderer.width, rh: app.renderer.height,
    };
  }
  fit();
  requestAnimationFrame(fit);
  setTimeout(fit, 250);
  window.addEventListener('resize', fit);
  if (typeof ResizeObserver !== 'undefined') {
    try { new ResizeObserver(fit).observe(canvas.parentElement); } catch (e) {}
  }

  canvas.style.cursor = 'pointer';

  // 让角色填满舞台并居中。

  canvas.style.cursor = 'pointer';
  canvas.addEventListener('click', onPoke);
  canvas.addEventListener('dblclick', e => { e.preventDefault(); onNudge(); });
  setExpr('star', true);
  say(PET_TEXT.star, 4000);
  motion('idle');

  if (cfg.pause_when_hidden) {
    document.addEventListener('visibilitychange', () => {
      try {
        if (document.hidden) PIXI.Ticker.shared.stop();
        else PIXI.Ticker.shared.start();
      } catch (e) { /* 忽略 */ }
    });
  }
  renderPlanBar(null);       // 先把控制条画出来（未开始状态）
  poll();
  setInterval(poll, 4000);
  setInterval(tick, 1000);
}

// 计划控制条：桌宠这边也能直接开始/暂停/结束专注。
// 以前只有仪表盘能操作 —— 桌宠只能看不能动，想暂停还得切到浏览器。
function renderPlanBar(p) {
  const bar = $('planbar');
  if (!bar) return;
  const active = !!(p && p.active);
  const isBreak = !!(p && p.is_break);
  const sig = [active, isBreak, active ? p.round : 0,
               active ? Math.round((p.remaining_sec || 0) / 60) : 0].join('|');
  if (bar.dataset.sig === sig) return;      // 没变化就别重建，免得按钮被点掉
  bar.dataset.sig = sig;
  bar.innerHTML = '';

  const mkBtn = (text, cls, fn, title) => {
    const b = document.createElement('button');
    b.textContent = text;
    if (cls) b.className = cls;
    if (title) b.title = title;
    b.onclick = fn;
    bar.appendChild(b);
    return b;
  };

  if (!active) {
    mkBtn('开始专注', 'primary', () => planAction({action: 'start'}, '开始专注'),
          '按你在仪表盘里设定的节奏开始一轮');
    const info = document.createElement('span');
    info.className = 'pinfo';
    info.textContent = p && p.finished && p.stop_reason ? '上次已结束' : '';
    bar.appendChild(info);
    return;
  }

  mkBtn(isBreak ? '结束休息，继续' : '提前休息', '', () =>
    planAction({action: 'skip'}, isBreak ? '继续专注' : '提前休息'),
    isBreak ? '跳过休息直接进入下一轮' : '跳过剩余时间，直接去休息');
  mkBtn('结束计划', 'warn', () => planAction({action: 'stop'}, '结束计划'),
        '结束这一轮专注计划（不影响监督）');
  const info = document.createElement('span');
  info.className = 'pinfo';
  const s = Math.max(0, Number(p.remaining_sec) || 0);
  const clock = String(Math.floor(s / 60)).padStart(2, '0') + ':' +
                String(s % 60).padStart(2, '0');
  info.textContent = (isBreak ? '休息 ' : '专注 ') + clock;
  bar.appendChild(info);
}

async function planAction(body, label) {
  try {
    const r = await fetch('/api/plan', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    say(label + '：' + (d.message || (d.ok ? '已执行' : '失败')), 6000);
    await poll();
  } catch (e) {
    say('操作失败：' + (e && e.message ? e.message : e), 6000);
  }
}

async function poll() {
  if (failed) return;
  try {
    const d = await (await fetch('/api/pet')).json();
    plan = d.plan || null;
    renderPlanBar(plan);
    const ev = d.event || null;
    if (ev && ev.seq > lastSeq) {
      lastSeq = ev.seq;
      react(ev);
      return;
    }
    if (Date.now() < bubbleUntil) return;   // 还在演刚发生的事
    const key = decideKey(d);
    setExpr(key);
    if (!plan || !plan.active) say(PET_TEXT[key] || '', 0);
  } catch (e) { /* 服务没起来时静默重试 */ }
}

// 决定当前该用哪个表情。规则与仪表盘、lib/avatars.py 保持一致：
// 只有"刚从不专注切回专注"才给鼓励。
function decideKey(d) {
  const p = d.plan || {};
  if (p.finished) return 'done';
  if (p.active && p.is_break) return 'breakTime';
  const last = d.last;
  if (!last) return 'blank';
  const a = last.avatar || 'general';
  if (a === 'thumbsup') return 'sweat';
  if (a === 'celebrate') return 'done';
  if (a === 'relax') return 'breakTime';
  if (a === 'shortvideo') return 'offShort';
  if (a === 'gaming') return 'offGame';
  if (a === 'social') return 'offSocial';
  if (a === 'sleepy') return 'sleepy';
  if (a === 'general') return last.on_task ? 'star' : 'offGeneral';
  return 'star';
}

function react(ev) {
  const card = ev.card || 'general';
  const key = setExpr(card, true);
  if (cfg.speak) {
    say(ev.activity || PET_TEXT[key] || '', 30000);
  }
  if (ev.kind === 'plan_done') motion('bubble');
  else if (ev.kind === 'break_start') motion('ketchup');
  else if (ev.kind === 'reminder' || ev.kind === 'off_task') motion('splash');
  const t = $('bar') && $('bar').querySelector('.title');
  // 只显示场景名。之前还带上了 ev.time（形如 00:02:21），看上去像个
  // 意味不明的计时器，而且和下面的番茄钟倒计时容易混。
  if (t) t.textContent = PET_CARD_LABEL[card] || '鲸鱼娘';
}

// 每秒：气泡在"刚发生的事"和"番茄钟倒计时"之间切换
function tick() {
  if (failed || !cfg.show_plan) return;
  if (Date.now() < bubbleUntil) return;
  const p = plan;
  if (!p || !p.active) return;
  const s = Math.max(0, Number(p.remaining_sec) || 0);
  const clock = String(Math.floor(s / 60)).padStart(2, '0') + ':' +
                String(s % 60).padStart(2, '0');
  const round = p.target_rounds ? `第 ${p.round}/${p.target_rounds} 轮`
                                : `第 ${p.round} 轮`;
  say(p.is_break
    ? `休息中 ${clock}｜${round} — 离开屏幕走两步吧`
    : `专注中 ${clock}｜${round} — 我盯着呢`, 0);
  p.remaining_sec = s - 1;   // 本地下走，否则数字会停在轮询那一刻
  // 控制条右侧的倒计时也跟着走。它按"分钟数"做签名，
  // 所以只在跨分钟时重建，不会每秒把按钮重建一遍（否则点击会丢）。
  renderPlanBar(p);
}

boot();
