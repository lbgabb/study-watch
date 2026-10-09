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

// 把未捕获的错误显示在气泡里。
// 为什么需要：boot() 是 async 的，抛出的异常只会进控制台 ——
// 而这是个无边框小窗，用户看不到控制台，界面就永远停在
// "正在把鲸鱼娘请出来…"（实测为排查这个花了不少时间才发现是启动静默失败）。
// 顺手存到 window.__petErr，测试脚本可以直接读。
window.__petErr = null;
// ---------- 右键菜单：逐个试表情与动作 ----------
// 为什么要这个：模型里有 15 个表情、8 个动作，但大部分要等特定场景才会出现，
// 用户没法主动看全。右键就能挨个试，也方便挑"哪个更好看"再决定怎么接触发。
const MENU_EXPRS = [
  ['star', '星星眼'], ['heart', '爱心眼'], ['excited', '开心兴奋'],
  ['tease', '调皮'], ['tongue', '吐舌'], ['angry', '生气'],
  ['cry', '哭'], ['sad', '悲伤'], ['dizzy', '晕晕'],
  ['sleepy', '闭眼口水'], ['blank', '呆呆眼'], ['sweat', '流汗'],
  ['question', '问号'], ['dark', '阴暗'], ['blush', '脸红'],
];
const MENU_MOTIONS = [
  ['idle', '待机'], ['bubble', '吹泡泡'], ['splash', '喷水'],
  ['selfie', '自拍'], ['selfieQuick', '快速自拍'], ['ketchup', '挤番茄酱'],
  ['openLid', '开盖'], ['aidale', '打瞌睡'],
];

function markMenu(kind, id) {
  const menu = $('menu');
  if (!menu) return;
  for (const b of menu.querySelectorAll('button')) {
    b.classList.toggle('on', kind === 'expr' ? b.dataset.expr === id
                                             : b.dataset.motion === id);
  }
}

function buildMenu() {
  const menu = $('menu');
  if (!menu || menu.dataset.built) return;
  menu.dataset.built = '1';
  const addHead = txt => {
    const d = document.createElement('div');
    d.className = 'h';
    d.textContent = txt;
    menu.appendChild(d);
  };
  addHead('表情（' + MENU_EXPRS.length + '）');
  for (const [id, label] of MENU_EXPRS) {
    const b = document.createElement('button');
    b.textContent = label + '  ' + id;
    b.dataset.expr = id;
    b.onclick = () => {
      bubbleUntil = 0;              // 让位给手动挑选
      const key = setExpr(id, true);
      say('手动切换表情：' + label + '（' + key + '）', 5000);
      markMenu('expr', id);
    };
    menu.appendChild(b);
  }
  addHead('动作（' + MENU_MOTIONS.length + '）');
  for (const [id, label] of MENU_MOTIONS) {
    const b = document.createElement('button');
    b.textContent = label + '  ' + id;
    b.dataset.motion = id;
    b.onclick = () => {
      motion(id);
      say('播放动作：' + label + '（' + id + '）', 5000);
      markMenu('motion', id);
    };
    menu.appendChild(b);
  }
  addHead('其他');
  const b = document.createElement('button');
  b.textContent = '恢复自动表情';
  b.onclick = () => {
    bubbleUntil = 0;
    hideMenu();
    poll();
    say('好了，我按你的状态来。', 4000);
  };
  menu.appendChild(b);
}

function showMenu(x, y) {
  const menu = $('menu');
  if (!menu) return;
  const root = $('root');
  const box = root ? root.getBoundingClientRect() : {width: 380, height: 480};
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.classList.add('on');
  const r = menu.getBoundingClientRect();
  // 别超出窗口：先摆再按实际尺寸收回来
  if (r.right > box.width) menu.style.left = Math.max(2, box.width - r.width - 4) + 'px';
  if (r.bottom > box.height) menu.style.top = Math.max(2, box.height - r.height - 4) + 'px';
}

function hideMenu() {
  const menu = $('menu');
  if (menu) menu.classList.remove('on');
}

function petFail(where, e) {
  const msg = (e && (e.stack || e.message)) || String(e);
  window.__petErr = where + ': ' + msg;
  const el = document.getElementById('say');
  if (el) el.textContent = '桌宠启动出错（' + where + '）：' + msg.slice(0, 160);
  const tag = document.getElementById('petTag');
  if (tag) tag.textContent = '出错';
  try { console.error('[pet]', where, e); } catch (_) {}
}
window.addEventListener('error', ev => petFail('window', ev.error || ev.message));
window.addEventListener('unhandledrejection',
  ev => petFail('promise', ev.reason || 'unknown rejection'));

const PET_EXPR = {
  onTask: 'star', comeback: 'sweat', offGeneral: 'tease', offShort: 'tongue',
  offGame: 'angry', offSocial: 'tease', idle: 'blank', sleepy: 'sleepy',
  breakTime: 'heart', done: 'excited',
};

// 新接上的几个表情的台词（原来是模型里有、但没人触发）
const PET_TEXT_EXTRA = {
  cry: '连续好几次了。要不先休息一下？',
  dark: '夜深了，早点睡比多熬一小时有用。',
  question: '这条我有点拿不准，你自己看看。',
  dizzy: '我眼睛都转晕了，你也歇会儿吧。',
  sad: '这一段时间都不太行啊，要不要换个地方学？',
  blush: '行吧，这段时间表现不错。',
};

const PET_TEXT = Object.assign({
  star: '在状态，看着挺像样的。',
  sweat: '刚才还在别处，现在回来了——这就对了。',
  tease: '哎呀呀，又在开小差呢。',
  tongue: '再刷一个就学习？你上一个「再刷一个」是二十分钟前说的。',
  angry: '这局不算，那下一局呢。存档不会跑，作业会。',
  blank: '盯着屏幕发呆不算学习，也不算休息。',
  sleepy: '困了就别硬撑，起身走两步。',
  heart: '这轮结束了，去休息。',
  excited: '计划完成，干得漂亮。',
}, PET_TEXT_EXTRA);

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
  try {
    em.setExpression(key);
    exprNow = key;
    window.__petExprErr = null;
  } catch (e) {
    // **不要静默吞掉**：以前这里只把 exprNow 清空，结果表情切换失败时
    // 界面毫无反应也查不出原因。现在把错误留下来（菜单与测试都能读）。
    exprNow = '';
    window.__petExprErr = key + ': ' + ((e && e.message) || String(e));
    try { console.warn('[pet] setExpression failed', key, e); } catch (_) {}
  }
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
  // 等布局稳定再量尺寸（boot 是脚本一加载就调的，那一刻 flex 可能还没算完，
  // 量到过期值会让模型画偏）。
  //
  // **但不能只用 requestAnimationFrame**：这个窗口是 app 模式启动的，
  // 初始 document.hidden 为 true，rAF 一次都不会触发 —— 实测 boot() 会
  // 永远卡在那一行，界面停在"正在把鲸鱼娘请出来…"，而且因为不是抛异常，
  // 连 unhandledrejection 都抓不到（排查了很久）。
  // 所以 rAF 与定时器赛跑，谁先到用谁。
  await Promise.race([
    new Promise(r => requestAnimationFrame(() => r('raf'))),
    new Promise(r => setTimeout(() => r('timeout'), 120)),
  ]);
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
  // 右键：试表情与动作
  buildMenu();
  document.addEventListener('contextmenu', e => {
    e.preventDefault();
    showMenu(e.clientX - (window.screenX - window.screenX), e.clientY);
  });
  document.addEventListener('click', e => {
    const menu = $('menu');
    if (menu && menu.classList.contains('on') && !menu.contains(e.target)) hideMenu();
  });
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
//
// 按优先级从"具体"到"笼统"：连续分心 > 深夜 > 判定不确定 > 类别。
function decideKey(d) {
  const p = d.plan || {};
  if (p.finished) return 'done';

  const last = d.last;
  // --- 优先看更具体的信号 ---
  // 连续分心 3 次以上：光吐槽已经没用了，换成"哭"
  if (last && !last.on_task && (d.off_streak || 0) >= 3) return 'cry';
  // 深夜还在跑神：提示该睡了（正常熬夜学习不打扰）
  if (last && !last.on_task && d.night) return 'dark';
  // 判定置信度很低：它自己也没把握，用问号比乱下结论好
  if (last && typeof last.confidence === 'number' && last.confidence > 0
      && last.confidence < 0.55) return 'question';

  if (p.active && p.is_break) return 'breakTime';
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
