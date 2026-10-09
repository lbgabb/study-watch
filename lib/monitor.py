"""学习监督主程序。

用法：
  python monitor.py                  # 开始监督（Ctrl+C 结束并打印小结）
  python monitor.py --minutes 25     # 只监督 25 分钟（番茄钟）
  python monitor.py --once           # 立刻判一次并打印结果（测试用，1 次 API 调用）
  python monitor.py --dry-run        # 只测截图/窗口采集，不调用 API、不产生费用
  python monitor.py --report         # 打印今日日报
  python monitor.py --report --days 7
  python monitor.py --export         # 导出今日 Markdown 日报
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import date, datetime
from pathlib import Path

if __package__ in (None, ""):  # 允许 python monitor.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    __package__ = "lib"

from . import policy, proc, report, state as state_mod, store, vision, winapi  # noqa: E402
from . import plan as plan_mod  # noqa: E402
from .config import ROOT, load_config  # noqa: E402
from .config import CONFIG_PATH  # noqa: E402
from .notify import Notifier  # noqa: E402

STATUS_LABEL = {
    "ok": "判定完成",
    "error": "判定失败",
    "idle_skip": "空闲跳过",
    "locked_skip": "锁屏跳过",
    "own_window": "提醒窗在前台",
    "policy_skip": "按应用策略不判定",
    "policy_wait": "按应用策略等待",
}


# ---------------------------------------------------------------- 日志
_LOG_FILE: Path | None = None


def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except Exception:
            pass
    if _LOG_FILE is not None:
        try:
            with _LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------- 单次判定
def do_check(cfg: dict, api_key: str, notifier: Notifier | None, dry: bool) -> dict:
    """注意：调用方需保证不会有更高优先级的分支抢先处理，本函数专注于判定流程。"""
    ctx = winapi.foreground_window()
    idle = winapi.idle_seconds()
    idle_skip = float(cfg.get("idle_skip_sec", 300))
    if idle_skip and idle > idle_skip:
        rec = {"status": "idle_skip", "idle_sec": round(idle, 1),
               "title": ctx["title"], "process": ctx["process"]}
        log(f"{STATUS_LABEL['idle_skip']}：{idle / 60:.1f} 分钟无输入（{ctx['process'] or '未知'}），本次不计入统计")
        return rec

    if winapi.is_session_locked():
        rec = {"status": "locked_skip", "title": ctx["title"], "process": ctx["process"]}
        log(f"{STATUS_LABEL['locked_skip']}：屏幕已锁定，本次不计入统计")
        return rec

    shot = vision.capture(cfg, save_dir=(ROOT / cfg["privacy"]["shots_dir"])
                          if cfg["privacy"].get("save_shots") else None)
    raw_w, raw_h = shot["raw_size"]
    sent_w, sent_h = shot["sent_size"]
    log(f"截图 {raw_w}x{raw_h} -> {sent_w}x{sent_h} / {shot['bytes'] / 1024:.0f} KB"
        f"｜前台：{ctx['process'] or '未知'}")

    if dry:
        log("--dry-run：已跳过 API 调用（未产生费用）")
        return {"status": "dry_run", "title": ctx["title"], "process": ctx["process"],
                "bytes": shot["bytes"]}

    try:
        started = time.time()
        verdict = vision.judge(cfg, api_key, shot, ctx)
    except Exception as e:
        log(f"{STATUS_LABEL['error']}：{e}")
        return {"status": "error", "error": str(e), "title": ctx["title"],
                "process": ctx["process"], "interval_sec": cfg["interval_sec"]}

    cost = time.time() - started
    tag = "在状态" if verdict["on_task"] else "分心"
    log(f"{tag}｜{verdict['category']}｜{verdict['activity']}")
    log(f"     依据：{verdict['basis'][:100]}")
    log(f"     {verdict['latency_ms'] / 1000:.1f}s 内返回（累计 {cost:.1f}s）"
        f"｜tokens {verdict['tokens_in']}/{verdict['tokens_out']}｜${verdict['cost_usd']:.4f}")

    rec = {
        "status": "ok",
        "title": ctx["title"],
        "process": ctx["process"],
        "idle_sec": round(idle, 1),
        "shot_size": f"{sent_w}x{sent_h}",
        "shot_bytes": shot["bytes"],
        "shot_path": shot["shot_path"],
        "interval_sec": cfg["interval_sec"],
        "raw_path": store.save_raw(cfg, verdict),
        **verdict,
    }

    # 提醒策略：连续 N 次判定为分心才提醒（N=1 即立刻提醒）
    need = int(cfg.get("reminder", {}).get("off_task_streak_required", 1) or 1)
    rec["reminded"] = False
    if notifier is not None and not verdict["on_task"] and need <= 1:
        # 番茄钟的休息时段默认不提醒：休息就该离开屏幕，
        # 这时候弹"你分心了"只会让人干脆不休息（可在计划里打开 remind_on_break）
        p = plan_mod.load()
        in_break = bool(p is not None and not p.finished and p.is_break)
        if not (in_break and not p.remind_on_break):
            notifier.notify(verdict, goal=cfg["judge"].get("goal", ""))
            rec["reminded"] = True
    return rec


def _notify_phase(notifier: Notifier | None, title: str, body: str, cfg: dict,
                  *, card_key: str = "", event: str = "") -> None:
    """阶段切换 / 计划完成的通知。

    优先用同一个置顶提醒窗（带按钮，用户能确认），失败再退回系统通知。
    这里的 verdict 是"合成"的：只借窗口的展示能力，不代表一次分心判定。

    card_key 指定用哪张角色卡片（庆祝/休息/鼓励）。注意这类通知**不走静音**：
    正反馈被静音吞掉的话，用户永远只看到批评。
    """
    fake = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "activity": body.split("\n")[0],
        "basis": body.replace("\n", "　"),
        "category": title,
        "on_task": True,
        "confidence": 0,
        "cost_usd": 0,
        "process": "",
    }
    try:
        if notifier is not None:
            notifier.notify(fake, goal=cfg.get("judge", {}).get("goal", ""),
                            card_key=card_key, event=event)
            return
    except Exception:
        pass
    try:
        from .notify import _toast
        _toast(title, body.replace("\n", " "))
    except Exception:
        pass


def _maybe_streak_remind(cfg: dict, notifier: Notifier | None, rec: dict) -> None:
    """连续 N 次分心才提醒的模式（N>1）：记录已落盘，回看最近 N 条。"""
    need = int(cfg.get("reminder", {}).get("off_task_streak_required", 1) or 1)
    if notifier is None or need <= 1 or notifier.muted:
        return
    recs = [r for r in store.load_day(cfg, date.today()) if r.get("status") == "ok"]
    if len(recs) >= need and all(not r.get("on_task", True) for r in recs[-need:]):
        notifier.notify(rec, goal=cfg["judge"].get("goal", ""))
        rec["reminded"] = True


def _init_log_file() -> None:
    """让 --once / --dry-run / 主循环都写同一份日志，避免调试路径无迹可查。"""
    global _LOG_FILE
    if _LOG_FILE is None:
        log_dir = ROOT / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        _LOG_FILE = log_dir / "watch.log"


def _pid_file() -> Path:
    return ROOT / "data" / "monitor.pid"


def _pause_file() -> Path:
    """暂停标记：文件存在即暂停判定（进程还活着，只是不打分、不花钱）。"""
    return ROOT / "data" / "paused"


def _is_paused() -> bool:
    return _pause_file().exists()


def _write_pid_file(args_summary: str) -> None:
    """记下自己在跑，供仪表盘/启动器判断是否已在监督（CIM 查不到时的兜底）。"""
    if not args_summary.strip():
        return
    try:
        _pid_file().write_text(
            json.dumps({"pid": os.getpid(), "args": args_summary,
                        "started": datetime.now().isoformat(timespec="seconds")},
                       ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def _clear_pid_file() -> None:
    try:
        rec = json.loads(_pid_file().read_text(encoding="utf-8"))
        if int(rec.get("pid", 0)) == os.getpid():
            _pid_file().unlink()
    except (OSError, ValueError, json.JSONDecodeError):
        pass


# ---------------------------------------------------------------- 主循环
def _cli_overrides(cfg: dict) -> dict:
    """命令行显式指定的项，优先于配置文件（面板改配置不该覆盖命令行意图）。"""
    return {"interval_sec": cfg.get("interval_sec")}


def _apply_overrides(cfg: dict, overrides: dict) -> dict:
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v
    return cfg


def run(cfg: dict, minutes: float | None, dry: bool, background: bool) -> int:
    _init_log_file()

    overrides = _cli_overrides(cfg)
    api_key = "" if dry else vision.resolve_api_key(cfg)
    if not dry:
        log(f"模型 {cfg['api']['model']}｜每 {cfg['interval_sec']} 秒判定一次"
            f"｜目标：{cfg['judge']['goal']}")
        log(f"提醒后端：{'置顶窗口' if cfg.get('reminder', {}).get('enabled') else '已关闭'}")

    notifier = None
    if cfg.get("reminder", {}).get("enabled", True) and not dry:
        notifier = Notifier(cfg)

    if background:
        winapi.hide_console()
        log("已转入后台运行（结束请用任务管理器结束 python 进程，或从托盘/任务栏恢复）")

    args_summary = f"--background{f' --minutes {minutes}' if minutes else ''}"
    _write_pid_file(args_summary)
    pause_logged = False

    history: list[dict] = []
    counts = {"ok": 0, "error": 0, "skip": 0, "off": 0, "policy_skip": 0}
    cost = 0.0
    started = time.time()
    deadline = started + minutes * 60 if minutes else None
    stopping = False
    st = state_mod.load()          # 上次判定时间/上次前台应用，跨重启续上
    last_policy_key: tuple | None = None

    def _stop(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True

    try:
        import signal
        signal.signal(signal.SIGINT, _stop)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _stop)
    except (ValueError, OSError):
        pass

    plan_last_phase: str | None = None
    plan_announced: set[str] = set()

    while not stopping:
        try:
            if deadline and time.time() >= deadline:
                log("监督时段已结束")
                break

            # 每轮重读配置：这样在仪表盘控制面板里改设置，不用重启监督就能生效
            # （命令行显式传的 --interval 等仍然优先，不被文件覆盖）
            try:
                cfg = _apply_overrides(load_config(), overrides)
            except SystemExit as e:      # 配置文件被改坏了：保留旧配置继续跑
                log(f"配置读取失败，沿用上一份配置：{e}")
            if notifier is not None:
                notifier.cfg = cfg

            # ---- 番茄钟 / 专注计划：到点就推进阶段 ----
            plan = plan_mod.load()
            if plan is not None and not plan.finished:
                now_ts = time.time()
                if now_ts >= plan.phase_ends_at:
                    was = plan.phase_label()
                    plan = plan_mod.advance(plan, now=now_ts)
                    if plan.finished:
                        log(f"专注计划完成：共 {plan.done_focus_rounds()} 轮专注")
                        _notify_phase(notifier, "计划完成",
                                      f"共完成 {plan.done_focus_rounds()} 轮专注，"
                                      f"辛苦了。要再来一轮就在仪表盘上点开始。", cfg,
                                      card_key="celebrate", event="plan_done")
                    else:
                        log(f"{was}结束 -> 进入{plan.phase_label()}"
                            f"（第 {plan.round} 轮，{plan.phase_sec // 60} 分钟）")
                        _notify_phase(
                            notifier,
                            f"{was}结束",
                            (f"去休息 {plan.phase_sec // 60} 分钟，起来走动、看远处。\n"
                             f"休息时不会提醒你分心。"
                             if plan.is_break else
                             f"开始第 {plan.round} 轮专注，{plan.phase_sec // 60} 分钟。"),
                            cfg,
                            card_key="relax" if plan.is_break else "thumbsup",
                            event="break_start" if plan.is_break else "phase_focus")
                # 阶段切换的即时播报（含刚开始的那一轮）
                if plan.phase != plan_last_phase:
                    plan_last_phase = plan.phase
                    if plan.phase_label() not in plan_announced or plan.round not in plan_announced:
                        log(f"专注计划：{plan.phase_label()}｜第 {plan.round} 轮"
                            f"｜剩 {plan.remaining_sec() // 60} 分钟"
                            + (f"｜主题：{plan.note}" if plan.note else ""))
                        plan_announced.add(plan.phase_label())
                        plan_announced.add(plan.round)

            ctx = winapi.foreground_window()
            own_pid = winapi.own_pid()
            if _is_paused():
                # 暂停：进程继续待命，但不截图、不判定、不花钱
                if not pause_logged:
                    log("已暂停判定（进程仍在待命，恢复后继续）")
                    pause_logged = True
            elif ctx["pid"] == own_pid:
                log(f"{STATUS_LABEL['own_window']}（{ctx['title'][:30]}），稍后再判")
            else:
                if pause_logged:
                    log("已恢复判定")
                    pause_logged = False

                # 按前台应用分配截图：决定这一轮要不要真截图 + 调模型
                decision = policy.decide(
                    cfg, ctx,
                    now=datetime.now(),
                    last_ok=policy.parse_ts(st.get("last_ok")),
                    last_app_key=st.get("last_app"),
                    last_app_seen=policy.parse_ts(st.get("last_app_seen")),
                )
                if not decision["capture"]:
                    counts["policy_skip"] += 1
                    key = (decision["reason"], decision["app"])
                    if key != last_policy_key and not dry:
                        log(f"{decision['reason']}：{decision['app']}"
                            + (f"（规则：{decision['rule']}）" if decision["rule"] else "")
                            + "，本轮不截图")
                        last_policy_key = key
                    state_mod.record_seen(st, app=decision["app"], hwnd=ctx.get("hwnd"))
                else:
                    if last_policy_key is not None:
                        log(f"恢复判定（{decision['reason']}）")
                        last_policy_key = None
                    rec = do_check(cfg, api_key, notifier, dry)
                    if decision["reason"] not in ("全局间隔到期",):
                        rec["policy_reason"] = decision["reason"]
                        rec["policy_rule"] = decision["rule"]
                    # 把当前处于计划的哪个阶段写进记录：
                    # 休息时的判定不计入专注率，否则好好休息反而拉低统计
                    plan_now = plan_mod.load()
                    phase, plan_extra = plan_mod.phase_for(plan_now)
                    if phase:
                        rec["plan_phase"] = phase
                        rec.update(plan_extra)
                        if plan_now is not None and plan_now.is_break and not plan_now.strict_break:
                            rec["exclude_from_stats"] = True
                    if rec.get("status") != "dry_run":
                        store.append(cfg, rec)
                    st_now = datetime.now()
                    if rec.get("status") == "ok":
                        state_mod.record_capture(st, app=decision["app"],
                                                 hwnd=ctx.get("hwnd"), when=st_now)
                    else:
                        state_mod.record_seen(st, app=decision["app"],
                                              hwnd=ctx.get("hwnd"), when=st_now)
                    st["last_checked"] = st_now.isoformat(timespec="seconds")
                    state_mod.save(st)
                    st = state_mod.load()
                    stl = rec.get("status")
                    if stl == "ok":
                        counts["ok"] += 1
                        cost += float(rec.get("cost_usd") or 0)
                        history.append(rec)
                        if not rec.get("on_task"):
                            counts["off"] += 1
                            # 计划的休息时段不打扰：休息本来就该离开屏幕，
                            # 这时候弹"你分心了"只会让人干脆不休息
                            in_break = bool(rec.get("plan_phase") in ("break", "long_break"))
                            allow = True
                            if in_break:
                                p_now = plan_mod.load()
                                allow = bool(p_now and p_now.remind_on_break)
                            if allow and not rec.get("exclude_from_stats"):
                                _maybe_streak_remind(cfg, notifier, rec)
                    elif stl == "error":
                        counts["error"] += 1
                    else:
                        counts["skip"] += 1

            # 睡眠期间要能及时响应：暂停/停止、阶段切换（专注→休息）、提醒窗事件
            sleep_left = cfg["interval_sec"]
            while sleep_left > 0 and not stopping:
                if notifier is not None:
                    notifier.pump()
                if deadline and time.time() >= deadline:
                    break
                # 阶段剩余时间比 interval 短时，只睡到阶段结束，好让切换及时发生
                p = plan_mod.load()
                if p is not None and not p.finished:
                    left = p.remaining_sec()
                    if 0 < left < sleep_left:
                        sleep_left = left
                    if left <= 0:
                        break
                step = 0.4 if notifier is not None else 0.5
                time.sleep(min(step, sleep_left))
                sleep_left -= step
        except KeyboardInterrupt:
            break
        except Exception as e:  # 单次异常不能让监督停摆
            log(f"循环异常：{type(e).__name__}: {e}")
            time.sleep(5)

    elapsed = time.time() - started
    log("")
    log(f"本次监督结束：运行 {report.fmt_dur(elapsed)}｜判定 {counts['ok']} 次"
        f"｜分心 {counts['off']} 次｜失败 {counts['error']} 次｜跳过 {counts['skip']} 次"
        f"｜按应用策略省下 {counts['policy_skip']} 次判定"
        f"｜花费 ${cost:.4f}")
    if counts["ok"]:
        log("")
        for line in report.render_day(store.load_day(cfg, date.today())).splitlines():
            log(line)
    if notifier is not None:
        notifier.destroy()
    _clear_pid_file()
    return 0


# ---------------------------------------------------------------- 策略排查
def show_policy(cfg: dict) -> int:
    """打印当前前台应用会命中哪条规则、这一轮会不会截图。用于调规则。"""
    import json as _json
    cap = cfg.get("capture") or {}
    ctx = winapi.foreground_window()
    app = policy.normalize(ctx.get("process", "")) or "(未知)"
    rule = policy.find_rule(cap.get("rules") or [], ctx)
    st = state_mod.load()
    now = datetime.now()
    decision = policy.decide(cfg, ctx, now=now,
                             last_ok=policy.parse_ts(st.get("last_ok")),
                             last_app_key=st.get("last_app"),
                             last_app_seen=policy.parse_ts(st.get("last_app_seen")))

    print("=== 前台应用 ===")
    print(f"  进程   {ctx.get('process') or '(未知)'}   -> 归一化 {app}")
    print(f"  标题   {(ctx.get('title') or '(无标题)')[:80]}")
    print(f"  hwnd   {ctx.get('hwnd')}")
    print()
    print("=== 策略状态 ===")
    print(f"  capture.enabled = {cap.get('enabled', True)}")
    print(f"  规则条数        = {len(cap.get('rules') or [])}")
    print(f"  全局间隔        = {cap.get('default_sec') or cfg.get('interval_sec')} 秒")
    print(f"  兜底 min_gap    = {cap.get('min_gap_sec')} 秒")
    print()
    print("=== 命中情况 ===")
    if rule:
        print(f"  命中规则：{policy.rule_label(rule)}")
        print("  " + _json.dumps(rule, ensure_ascii=False))
    else:
        print("  没有命中任何规则（走全局间隔）")
    print()
    print("=== 状态 ===")
    print(f"  上次判定    {st.get('last_ok') or '（无）'}")
    print(f"  上次应用    {st.get('last_app') or '（无）'}")
    print(f"  上次见到它  {st.get('last_app_seen') or '（无）'}")
    print()
    print("=== 这一轮的决定 ===")
    print(f"  {'会截图判定' if decision['capture'] else '不截图'}｜原因：{decision['reason']}"
          + (f"｜规则：{decision['rule']}" if decision["rule"] else ""))
    return 0


def show_status(cfg: dict) -> int:
    """快速体检：一眼看出"界面为什么不动"。"""
    import socket
    from urllib import request as _req

    print("=== 监控进程 ===")
    pids = _running_monitor_pids()
    if pids:
        print(f"  运行中：PID {', '.join(map(str, pids))}")
    else:
        print("  未运行  -> 在仪表盘点「开始监督」，或双击桌面「学习监督」")
    pidfile = _pid_file()
    if pidfile.exists():
        try:
            rec = json.loads(pidfile.read_text(encoding="utf-8"))
            alive = int(rec.get("pid", 0)) in pids
            print(f"  pid 文件：PID {rec.get('pid')}（{rec.get('started')}）"
                  + ("" if alive else "  <- 已退出，是残留文件"))
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    print()
    print("=== 仪表盘服务 ===")
    port = 8770
    listening = False
    with socket.socket() as s:
        s.settimeout(0.5)
        listening = s.connect_ex(("127.0.0.1", port)) == 0
    if listening:
        print(f"  运行中：http://127.0.0.1:{port}/")
        try:
            with _req.urlopen(f"http://127.0.0.1:{port}/api/data", timeout=8) as r:
                d = json.loads(r.read())
            print(f"  接口正常：state={d.get('state')}｜今日 {d['today']['checks']} 次判定")
        except Exception as e:
            print(f"  端口在听但接口异常：{type(e).__name__}: {e}")
    else:
        print(f"  未运行  -> 双击桌面「学习监督 仪表盘」启动")
        print("  （页面若开着会显示「仪表盘服务已断开」，服务起来后 5 秒内自动接上）")

    print()
    print("=== 配置是否真的生效 ===")
    cap = cfg.get("capture") or {}
    print(f"  配置文件：{CONFIG_PATH}")
    print(f"  判定间隔：{cfg['interval_sec']} 秒｜截图宽度 {cfg['max_width']}｜detail={cfg['detail']}")
    print(f"  空闲跳过：{cfg['idle_skip_sec']} 秒｜截图落盘：{cfg['privacy'].get('save_shots')}")
    print(f"  截图策略：{'开启' if cap.get('enabled', True) else '关闭'}"
          f"｜规则 {len(cap.get('rules') or [])} 条｜兜底 {cap.get('min_gap_sec')} 秒")

    print()
    print("=== 今天的数据 ===")
    recs = store.load_day(cfg, date.today())
    ok = [r for r in recs if r.get("status") == "ok"]
    print(f"  记录 {len(recs)} 条（判定成功 {len(ok)} 条）")
    if recs:
        last = recs[-1]
        print(f"  最近一条：{last.get('ts')} {last.get('status')} "
              f"{last.get('process') or ''} {str(last.get('activity') or '')[:40]}")
    return 0


def _running_monitor_pids(*, exclude_self: bool = True) -> list[int]:
    """纯 ctypes 找 monitor 进程；读不到 PEB 时再退回 PowerShell。

    exclude_self 很重要：--status / --stop 自己的命令行里也含 monitor.py，
    不过滤会把"我自己"当成"正在跑的监督"。
    """
    pids = proc.pids_matching("monitor.py")
    if not pids:
        import subprocess as _sp
        ps = ("Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" "
              "| Where-Object { $_.CommandLine -like '*monitor.py*' } "
              "| Select-Object -ExpandProperty ProcessId")
        try:
            out = _sp.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=20, creationflags=0x08000000).stdout
            pids = sorted(int(x) for x in out.split() if x.strip().isdigit())
        except Exception:
            return []
    if exclude_self:
        me = os.getpid()
        pids = [p for p in pids if p != me]
    return pids


def check_api_cli(cfg: dict) -> int:
    """换服务商/换模型后先跑这个，确认配置真的能通。"""
    api = cfg.get("api") or {}
    print("=== 当前配置 ===")
    print(f"  base_url : {api.get('base_url')}")
    print(f"  model    : {api.get('model')}")
    print(f"  key 来源 : {os.environ.get(api.get('api_key_env', 'DEEPSEEK_API_KEY')) and '环境变量' or '凭据文件'}")
    print()
    print("=== 用内置小图测试（不截屏、不读你的屏幕）===")
    try:
        r = vision.check_api(cfg)
    except Exception as e:
        print(f"  [失败] {e}")
        print()
        print("常见原因与处理：")
        print("  · 401/403 -> key 不对或该模型未开通")
        print("  · 404     -> base_url 少了 /v1，或 model 名字写错")
        print("  · 400     -> 该模型不支持图片输入，换一个视觉模型")
        print("  · 网络错误 -> 需要代理或该域名不可达")
        return 1

    print(f"  [通过] {r['latency_ms']} ms｜tokens {r['tokens_in']} 入 / {r['tokens_out']} 出")
    print(f"  JSON 解析：{'正常' if r['json_ok'] else '失败（模型没按 JSON 回，判定会被重试兜底，但建议换个模型）'}")
    data = r["parsed"]
    if r["json_ok"]:
        print(f"  模型看到的：{data.get('seen') or data.get('activity') or ''}")
        print(f"  判定字段：on_task={data.get('on_task')} category={data.get('category')} "
              f"confidence={data.get('confidence')}")
    else:
        print(f"  原始返回：{r['raw']}")
    print()
    print("说明：能通过这一项，说明协议兼容、模型支持视觉、JSON 也回得出来，监督就能正常跑。")
    return 0


def stop_running(cfg: dict) -> int:
    """停止所有在跑的监督进程。

    按命令行里是否含 monitor.py 识别，**不依赖解释器的安装路径**：
    早先的 stop.bat 是按解释器目录名特征匹配进程的，换台机器（Python 装在别处）就停不掉。
    """
    pids = _running_monitor_pids()          # 已排除自己
    if not pids:
        print("当前没有正在运行的监督进程。")
        return 0

    stopped, failed = [], []
    for pid in pids:
        ok = False
        try:
            os.kill(pid, signal.SIGTERM)
            ok = True
        except (OSError, AttributeError, ValueError):
            ok = False
        if not ok:
            try:
                import subprocess as _sp
                _sp.run(["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True, creationflags=0x08000000)
                ok = True
            except Exception:
                ok = False
        (stopped if ok else failed).append(pid)

    if stopped:
        print(f"已停止 {len(stopped)} 个监督进程：{', '.join(map(str, stopped))}")
    if failed:
        print(f"有 {len(failed)} 个没能停掉（可能需要管理员权限）：{', '.join(map(str, failed))}")
        return 1

    # 顺手清掉运行时标记，避免下次启动时状态自相矛盾
    for f in (_pause_file(), _pid_file()):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="学习监督助手：截屏 + 视觉模型判断你是否在学习")
    parser.add_argument("--minutes", type=float, default=None, help="只监督这么多分钟后自动结束")
    parser.add_argument("--once", action="store_true", help="立刻判定一次并打印结果")
    parser.add_argument("--dry-run", action="store_true", help="只截图与采集窗口，不调用 API")
    parser.add_argument("--report", action="store_true", help="打印日报")
    parser.add_argument("--days", type=int, default=1, help="配合 --report：统计最近 N 天")
    parser.add_argument("--export", action="store_true", help="导出今日 Markdown 日报")
    parser.add_argument("--background", action="store_true", help="隐藏控制台窗口运行")
    parser.add_argument("--policy", action="store_true",
                        help="显示当前前台应用会命中哪条截图规则、会不会判定")
    parser.add_argument("--status", action="store_true",
                        help="快速体检：监控进程、仪表盘服务、配置是否真的生效")
    parser.add_argument("--stop", action="store_true",
                        help="停止正在运行的监督进程（按命令行识别，不依赖解释器安装路径）")
    parser.add_argument("--check-api", action="store_true",
                        help="用一张内置小图自检当前服务商/模型是否可用（换 key/换模型后先跑这个）")
    parser.add_argument("--interval", type=int, default=None, help="覆盖判定间隔（秒）")
    parser.add_argument("--config", default=None, help="使用指定的配置文件（默认 config.json）")
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config) if args.config else None)
    if args.interval:
        cfg["interval_sec"] = max(10, args.interval)
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if args.report:
        if args.days > 1:
            print(report.render_range(cfg, args.days))
        else:
            recs = store.load_day(cfg, date.today())
            print(report.render_day(recs, date.today()))
            days = store.list_days(cfg)
            if len(days) > 1:
                print(f"\n（另有 {len(days) - 1} 天历史记录，用 --report --days 7 查看汇总）")
        return 0

    if args.export:
        p = report.export_markdown(cfg, date.today())
        print(f"已导出：{p}")
        return 0

    if args.policy:
        return show_policy(cfg)

    if args.status:
        return show_status(cfg)

    if args.check_api:
        return check_api_cli(cfg)

    if args.stop:
        return stop_running(cfg)

    if args.once or args.dry_run:
        _init_log_file()
        try:
            api_key = "" if args.dry_run else vision.resolve_api_key(cfg)
        except RuntimeError as e:
            print(f"错误：{e}")
            return 2
        rec = do_check(cfg, api_key, None, args.dry_run)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return 0

    try:
        vision.resolve_api_key(cfg)
    except RuntimeError as e:
        print(f"错误：{e}")
        return 2
    return run(cfg, args.minutes, False, args.background)


if __name__ == "__main__":
    sys.exit(main())
