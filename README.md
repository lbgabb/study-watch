# study-watch

> 中文文档见 [README.zh-CN.md](README.zh-CN.md)。

> Study on a Pomodoro rhythm while a vision model checks whether you're actually studying: every few minutes it grabs a screenshot and asks "what is this person doing?", pops up a reminder when you drift off, and logs every verdict into a reviewable timeline and daily report. **Verdicts taken during breaks are excluded from your stats** — taking an honest break shouldn't make your numbers look bad.

It does not guess from window titles. **The screenshot is actually sent to the model**, so "the title says Linear Algebra but the screen is a short-video feed" is caught.

![Focus plan](assets/pomodoro-card.png)

```
[00:10:23] screenshot 1440x900 -> 1440x900 / 167 KB | foreground: msedge.exe
[00:10:25] ON TASK | Study | Watching a mechanics revision lecture; the slide is deriving the parallel axis theorem
[00:10:25]     basis: lecture notes visible, "02 Moment of inertia - parallel axis theorem", formula J_z = J_zc + md²
[00:10:25]     returned in 2.5s | tokens 684/347 | $0.0006
```

- **Pomodoro / focus plan** (the centrepiece): four built-in rhythms (25/5, 90/20, 52/17, 15/3), automatic focus↔break switching, full customisation that **remembers your numbers**; breaks are excluded from the focus rate and never trigger a distraction popup
- **Windows desktop tool**, Python 3.10+, single third-party dependency (Pillow)
- **Not tied to any one vendor**: standard OpenAI-compatible protocol, so any vision-capable model works — including a local llama.cpp / LM Studio server
- **Per-application capture policy**: skip games entirely, check short-video sites on every window switch, chat every 10 minutes, reading every 5 — saves API calls and improves accuracy
- **Local web dashboard**: zoomable timeline, date switching, and every setting editable in the browser — no hand-editing config files
- Screenshots are **encoded in memory only** and sent straight to your API; nothing is written to disk by default
- The setup script checks your environment, **installs missing dependencies automatically** (falling back to mirrors when PyPI times out), and creates desktop shortcuts

The dashboard (screenshot uses synthetic demo data, not real records):

![Dashboard](assets/dashboard-preview.png)

---

## Contents

- [Quick start](#quick-start)
- [Pomodoro focus plan](#pomodoro-focus-plan)
- [The reminder (and yes, it's cute on purpose)](#the-reminder-and-yes-its-cute-on-purpose)
- [Desktop pet: the whale girl reacts to your state](#desktop-pet-the-whale-girl-reacts-to-your-state)
- [Capture policy: allocating checks per application](#capture-policy-allocating-checks-per-application)
- [The dashboard](#the-dashboard)
- [How a check works](#how-a-check-works)
- [Configuration](#configuration)
- [Using another API or a local model](#using-another-api-or-a-local-model)
- [Cost](#cost)
- [Privacy](#privacy)
- [Tests](#tests)
- [Known limits](#known-limits)
- [Repository layout](#repository-layout)
- [Development notes](#development-notes)
- [How this project was written](#how-this-project-was-written)
- [License](#license)

---

## Quick start

### One-shot setup (recommended)

```powershell
git clone https://github.com/lbgabb/study-watch.git
cd study-watch
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` walks through: check Windows → find Python → check `PIL`/`tkinter`/`winsound` →
**install Pillow if missing** (retrying via a mirror when the default index times out) →
check the API key → generate the icon if absent → create two desktop shortcuts →
run a **free** smoke test.

You're done when you see `=== result: N ok / 0 failed ===`.

### Manual

```powershell
python -m pip install -r requirements.txt          # Pillow only
$env:DEEPSEEK_API_KEY = "sk-xxxx"                  # or fill it in the dashboard's Settings panel
python monitor.py --check-api                      # verify the model works (built-in test image, no screenshot)
python monitor.py --minutes 25                     # monitor for 25 minutes
```

> Multiple Pythons installed, or want to pin one? Create `py-path.txt` in the project root with
> the full path to the interpreter on the first line (already in `.gitignore`).

### Day-to-day

| Entry point | What it does |
| --- | --- |
| Desktop shortcut **学习监督** ("study watch") | Starts monitoring silently in the background; won't double-start if already running |
| Desktop shortcut **学习监督 仪表盘** ("dashboard") | Opens the web dashboard at `http://127.0.0.1:8770/` |
| `stop.bat` | Stops background monitoring |
| `report.bat` | Prints today's report |

Useful commands:

```powershell
python monitor.py --status       # health check: processes, service, whether config took effect, today's numbers
python monitor.py --policy       # which capture rule the current foreground app matches
python monitor.py --check-api    # verify model connectivity with a built-in image (never your screen)
python monitor.py --once         # run a single check now
python monitor.py --stop         # stop monitoring (identifies processes by command line, works on any machine)
python monitor.py --report --days 7
python monitor.py --export       # export a Markdown report
```

---

## Pomodoro focus plan

The "focus plan" card at the top of the dashboard, or `pomodoro.ps1` from the command line.
It is more than a timer: **the plan state is written into every verdict record**, so you can
tell afterwards how good a given focus round actually was.

![Focus plan card](assets/pomodoro-card.png)

### Built-in rhythms, and what each is actually based on

| Preset | Rhythm | Basis (honest version) |
| --- | --- | --- |
| 25 / 5 | 25 min focus, 5 min break, long break every 4 rounds | Cirillo's practical method: shrink a task until it is small enough to start immediately. **Not an experimental finding** |
| 90 / 20 | 90 min focus, 20 min break | Kleitman's BRAC: alertness appears to cycle roughly every 90 minutes while awake. Observational support for the order of magnitude; individual variation is large |
| 52 / 17 | 52 min focus, 17 min break | DeskTime's 2014 observational statistics over their own users. Not a controlled trial, and subject to self-report bias |
| 15 / 3 | 15 min focus, 3 min break | A short sprint for bad days and hard-to-start tasks: pay the smallest possible price to get into the work |
| Custom | Whatever you enter | — |

More reliable than any specific number are the three things these share: **sustained attention has a
ceiling; a break has to actually leave the task; and fixing the durations removes the recurring
decision of when to rest.** Pick the one you can keep up — that matters more than picking the
"most scientific" one.

### A deliberate design choice: breaks don't count against you

Verdicts taken during a break are tagged `exclude_from_stats`. They are **not counted in the focus
rate or the category breakdown**; they are recorded separately as break time.

The reasoning is practical: if resting honestly makes your numbers look worse, you'll stop resting —
which defeats the purpose. Measured comparison (5 minutes of phone scrolling during a break):

```
break counted in stats : focus rate 44.4%
break excluded         : focus rate 100.0%   break recorded separately: 300s
```

For the same reason, **breaks do not trigger "you got distracted" popups by default**
(there's a checkbox to turn that on). A break means leaving the screen; a popup then only
teaches you not to take breaks.

### Using it

In the dashboard: pick a rhythm → optionally set rounds and a topic → start. While running you get a
ring countdown, round progress dots, and buttons for "take a break early", "break's over, continue",
and "end plan".

**Customisation persists.** Editing the focus / break / long-break numbers switches you to a custom
rhythm, and **the change is saved into the `plan` section of `config.json`** — close the browser,
restart the service, and your numbers are still there. Specific behaviours:

- Clicking "Custom" does **not** wipe the numbers you already set (it only marks the rhythm as custom)
- Selecting a concrete preset applies that preset's numbers
- When a plan starts, precedence is: **request > your saved values > preset defaults**

```powershell
.\start-25min.bat                                  # start one 25/5 round
powershell -File .\pomodoro.ps1 -Rounds 4 -Note "Chapter 3 exercises"
powershell -File .\pomodoro.ps1 -Preset ultradian  # 90/20
powershell -File .\pomodoro.ps1 -Focus 50 -Break 10
powershell -File .\pomodoro.ps1 -Status
powershell -File .\pomodoro.ps1 -Stop
```

The plan lives in `data/plan.json` and **resumes where it left off** if you restart the monitor —
it does not start over. `rounds: 0` means unlimited, until you stop it manually.

---

## The reminder (and yes, it's cute on purpose)

A cold "you got distracted" popup is easy to ignore and easier to resent — you just turn the tool
off. So the reminder has a face, and it teases you instead of scolding you.

![Reminder popup](assets/reminder-popup.png)

Eight hand-drawn cards, one per situation. Each one carries a different expression, so you can tell
what it's about before reading a word:

![Reminder cards](assets/reminder-faces.png)

| Card | When it shows up | Tone |
| --- | --- | --- |
| Caught you wandering | Anything that doesn't match a more specific card | tease |
| "Just one more"? | Process or window title matches a short-video site (TikTok, Shorts, Reels, Bilibili…) | tease |
| One more round? | Category is gaming | tease |
| Replying to just one message? | Category is social | tease |
| Tired is tired | Category is idle — staring at the screen, not doing anything | rest |
| That's the way | You drifted off **and came back** | praise |
| Round done — go rest | A focus round ended and the break started | rest |
| Plan complete. Nice work. | Every planned round finished | praise |

A few deliberate choices behind this:

- **Teasing beats scolding.** "Your last *just one more* was twenty minutes ago" lands better than
  "you are off task". You laugh, then go back to work. A tool that nags gets muted.
- **Praise is not muted.** The positive cards (came back / go rest / plan complete) ignore the
  "mute for N minutes" rule. Otherwise you'd only ever hear criticism, and you'd stop listening
  within two days.
- **The evidence always comes with it.** The card jokes; the line under it says what was actually on
  screen. Without that, this is just an app being rude for no reason.
- **No emoji in the copy** — the cards are rendered with a system font, and emoji turn into tofu
  boxes on some machines.

The same eight faces are reused across the dashboard, so the character that just complained at you
is the same one you see in the "Now" panel (64px, with a label), in the distraction list, and in the
recent-verdicts table (34px each). No extra artwork — it's the same files.

---

## Desktop pet: the whale girl reacts to your state

A live **Live2D whale girl** sits in the dashboard. She isn't decoration — **her expression follows the
verdict**, so you can tell what the last check concluded at a glance:

| State | Expression | What she says |
| --- | --- | --- |
| On task | starry eyes | Looking decent. Keep going. |
| Just came back | sweating | You were elsewhere, now you're back — that's the way. |
| Off task (general) | playful | Caught you wandering again. |
| Short videos | tongue out | "Just one more"? Your last one was twenty minutes ago. |
| Gaming | angry | One more round? Your save file will wait. Your deadline won't. |
| Idle / staring | blank eyes | Staring at the screen is neither studying nor resting. |
| Sleepy | eyes closed | Tired is tired. Stand up and walk a bit. |
| Break time | heart eyes | Round done — go rest. |
| Plan complete | excited | Plan complete. Nice work. |
| Repeated drifting | crying + water splash | That's several in a row. Maybe take a break? |

Click her and she reacts (bubble motion). **If WebGL or the assets are missing she simply doesn't
appear** — the rest of the dashboard is unaffected. The pet is a bonus; it must never break the
main feature.

### Why the pet lives in the browser, not in the reminder popup

The popup is built with `tkinter`, which **has no WebGL**, and Live2D cannot render without it.
Putting Live2D in the popup would mean either keeping a browser process alive and streaming
screenshots into tkinter (expensive), or switching to Electron/WebView2 (a few MB becomes 150MB+).
Neither is worth it. So the split is:

- **Reminder popup** (tkinter): static cards — zero dependencies, instant, cheap
- **Pet** (dashboard): real Live2D, because a browser is already running — **no extra process**

### Artwork and licensing (important)

The character artwork is **[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en)
(NonCommercial)** — **not** the same as this project's MIT. See [NOTICE.md](NOTICE.md) and
[PROVENANCE.md](PROVENANCE.md) for the layered terms.

**The character carries three layers of copyright, and all three must be credited:**

| Rights holder | Contribution |
| --- | --- |
| **上善无形 (Shangshan Wuxing)** | Original character design, the OC "溟月" |
| **ZipZipPipe** | The maid whale-girl redesign that adds the DeepSeek elements |
| **氵六青 (Bilibili UID 11272072)** | The Live2D rigging: binding, motions, expressions |

**This project is free, has no ads and sells nothing → that is non-commercial use, so the artwork may
be used.** But if you ever want to charge for it or monetise it, you **must delete `assets/live2d/`
and `assets/reminder/` first**.

Live2D Cubism Core is Live2D Inc.'s proprietary runtime (redistributable as part of a work); pixi and
pixi-live2d-display are MIT.

---

## Capture policy: allocating checks per application

Using the same interval for every application wastes calls — a video, a chat window and a code
editor change at completely different rates. Rules live in `capture.rules` in `config.json` and are
matched **in order; the first hit wins**:

```jsonc
"capture": {
  "enabled": true,
  "min_gap_sec": 20,       // safety gate: at least this long between two checks
  "rules": [
    // Don't check this application at all (games, emulators)
    { "name": "games", "process": ["steam", "mumup*", "pcl*", "minecraft*"],
      "action": "skip" },

    // Check the moment you switch to it (switch points are where drift happens)
    { "name": "short video", "title_contains": ["TikTok", "Shorts", "Reels"],
      "switch_check": true },

    // Windows you sit in for a long time: one check on arrival, then every 10 minutes
    { "name": "chat", "process": ["wechat*", "qq", "discord*", "telegram*"],
      "polling_sec": 600 },

    // Scrolling reading: check once N seconds have passed since the last verdict
    { "name": "long reads", "process": ["sumatrapdf*", "winword*", "wps*"],
      "tick_sec": 300 }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `process` / `process_contains` | Match by process name, `*` wildcard supported |
| `title` / `title_contains` | Match by window title (either may hit) |
| `action: "skip"` | **Never check** this application: no screenshot, no API call, not counted |
| `tick_sec: N` | Check only if N seconds have passed since the last verdict |
| `polling_sec: N` | Check once on arrival, then every N seconds |
| `switch_check: true` | Check immediately on every window switch to this application |

Applications matching no rule fall back to the global `interval_sec` — **with no rules configured
the behaviour is exactly the naive version**.

Reasons for skipping are logged, and summarised when monitoring ends:

```
not checking this application: notepad (rule: skip notepad), no screenshot this round
monitoring ended: ran 40s | 0 checks | 4 checks saved by policy | $0.0000 spent
```

State is kept in `data/state.json` and **carries across restarts**, so restarting the monitor
does not fire several checks back to back.

---

## The dashboard

Open `http://127.0.0.1:8770/` in a browser (the port walks forward if it's taken).

| Area | Contents |
| --- | --- |
| Summary cards | Today's focus rate, covered time, distraction count, spend |
| **Now / last of the day** | The most recent verdict — what you were doing — plus the evidence (text actually seen on screen) |
| **Timeline** | Category-coloured bars; upper row = on task, lower row = distracted. **Bar length is real duration**; zoomable, with a date picker |
| **Distraction list** | When you drifted, what you were doing, and the evidence; can follow the timeline window |
| Category breakdown / last 7 days / distraction sources / run stats | Donut, stacked bars, per-process ranking, tokens and cost |
| **Control panel** | Start / pause / stop / check once / export / open settings |

### Timeline: zoom and custom ranges

The timeline spans the whole day by default. Four ways to look closer:

| Action | Effect |
| --- | --- |
| **Date dropdown** (top left) | Switch the day being viewed (all days with records are listed); `?day=2026-10-08` opens a specific day directly and is bookmarkable |
| **Preset buttons** | Whole day / last 1, 3, 6, 12 hours. Anchored to "now" for today, and to **the end of that day's data** when viewing a past date |
| **Custom range** | Enter start and end (HH:MM) and press Apply; if start > end it is treated as crossing midnight (e.g. 22:00 → 02:00) |
| **Drag on the timeline** | Drag to select a span and zoom into it; the **mouse wheel** zooms around the cursor |
| Reset | Back to the whole day |

Details:

- Tick spacing is **adaptive**: hourly across a day, automatically switching to 10- and 5-minute
  steps once you zoom inside an hour
- When viewing today, a dashed "now" line is drawn for reference
- The heading live-updates with the current window and segment count, e.g. `23:35–00:01 | 12 segments`
- "Distractions" can be set to **follow the timeline window**, so you only see that span
- On a past date the header reads "last of YYYY-MM-DD (history)" and the summary cards switch to that
  day's numbers (the 7-day chart always reflects the current situation)

### The control panel's three states

| State | Meaning | Available actions |
| --- | --- | --- |
| Not monitoring | No monitor process | Start monitoring |
| Monitoring | Screenshot + verdict every N seconds | Pause judging, stop monitoring, check once, export, open settings |
| Paused | Process still alive but **not screenshotting and not spending**; resuming is instant | Resume, stop monitoring, open settings |

"Pause" simply stops judging while keeping the process; "stop" ends the monitor process entirely.
The service **respects your intent**: after you press stop, an externally killed monitor will not be
quietly resurrected by a status refresh.

### All settings live in the control panel

"Open settings" slides out a drawer, so **you never hand-edit `config.json`**:

| Group | What you can change | When it applies |
| --- | --- | --- |
| API key | See current state (masked, with its source), enter a new one and save | Immediately |
| Cadence | Check interval, idle-skip threshold, minimum gap, global interval override | Next check |
| Screenshots | Image detail, JPEG quality, scale width, whether to save to disk, whether to keep raw replies | Mostly next check |
| Judging criteria | Study goal, strictness, extra rules, category aliases | Next check |
| Reminders | On/off, sound, quiet period, how many consecutive misses before reminding, auto-close | Next check |
| API / model | base_url, model name, key env var, credentials file, timeout, max_tokens, temperature | **Requires restarting the monitor** |

Each field carries a badge saying whether it takes effect "next check" or "requires restart" — the
monitor **re-reads the config file every round**, so most settings apply on the next cycle without
a restart.

- **Test API connectivity** uses a built-in test image (**never your screen**) to validate
  base_url / model / key, and saves nothing
- **Save** writes only `config.json`; invalid values cause the **whole batch to be rejected** with reasons
- The key is stored in `data/secrets.json` (not in version control). Precedence: environment variable
  > panel-saved > credentials file
- Open the settings drawer directly: `http://127.0.0.1:8770/?settings=1`

---

## How a check works

One full round:

```
loop
 ├─ re-read config            (settings changed in the panel take effect here)
 ├─ check data/paused         → paused: do nothing this round
 ├─ check locked screen / long idle → yes: skip (no screenshot, no spend, not counted)
 ├─ ask the capture policy    → policy says no: skip
 ├─ screenshot (whole virtual desktop) → scale → JPEG → base64
 ├─ send image + "foreground process + window title" to the vision model
 ├─ parse the JSON verdict → append to log → pop a reminder if off task
 └─ sleep interval_sec → back to the top
```

The model is asked to return exactly one JSON object:

```json
{"activity":"one sentence on what is happening","category":"Study|Work|Entertainment|Social|Gaming|Shopping|Idle|Other",
 "on_task":true,"confidence":0.86,"basis":"quote specific text or UI elements actually visible on screen"}
```

A few rules are fixed in the prompt (editable in settings):

- **The picture wins**; the window title is only a hint — this is what stops "looks like study,
  is actually a short-video feed" from slipping through
- Short-video / recommendation-feed layouts (one video per screen, danmaku, like/coin buttons)
  **count as entertainment even when the content is educational**
- Lecture videos, textbook PDFs, problem sets, writing code, flashcards and note-taking count as study
- Locked screen / bare desktop / no sign of use counts as "idle"

The model occasionally emits invalid JSON. That is handled by a **tolerant repair pass**
(unescaped quotes, missing or duplicated commas, prose wrapped around the object), and if that
still fails the request is resent with a "you must output valid JSON" note.

Screenshot cost, measured on a 2880×1800 display: grab ~98ms + scale ~80ms + encode ~15ms ≈
**193ms**, JPEG ≈ 150 KB.

---

## Configuration

`config.json` (also editable in the dashboard):

```jsonc
{
  "interval_sec": 180,        // seconds between checks
  "idle_skip_sec": 300,       // skip if there has been no input for this long
  "max_width": 1600,          // screenshot scale width; smaller is cheaper
  "detail": "low",            // image detail: low is cheaper, high can read small text
  "capture": { /* see "Capture policy" above */ },
  "plan": {                   // pomodoro defaults, remembered from the dashboard
    "preset": "pomodoro", "focus_min": 25, "break_min": 5,
    "long_every": 4, "long_break_min": 20, "rounds": 0,
    "remind_on_break": false, "strict_break": false
  },
  "api": {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key_env": "DEEPSEEK_API_KEY",       // environment variable to read the key from
    "credentials_file": "~/.study-watch/credentials.yaml"
                                             // fallback yaml, e.g. DEEPSEEK_API_KEY: sk-xxxx
  },
  "judge": {
    "goal": "Exam preparation (lecture videos, textbooks, online courses, problem sets, programming/language study, homework and notes)",
    "strictness": "normal",   // loose / normal / strict
    "extra_rules": [],
    "alias_rules": []
  },
  "reminder": {
    "enabled": true, "sound": true,
    "mute_after_remind_sec": 300,
    "off_task_streak_required": 1,   // set to 2 to require two consecutive misses
    "auto_close_sec": 60
  },
  "privacy": {
    "save_shots": false,      // true writes screenshots to data/shots
    "save_api_raw": true      // keep raw model replies, useful for diagnosing misjudgements
  }
}
```

Environment variables override temporarily: `STUDY_WATCH_INTERVAL`, `STUDY_WATCH_MODEL`,
`STUDY_WATCH_BASE_URL`, `DEEPSEEK_API_KEY`.

---

## Using another API or a local model

This speaks the **standard OpenAI-compatible protocol** (`POST {base_url}/chat/completions`, Bearer
auth, images as base64 data URLs in `image_url`) — not a vendor-private API. **The only requirement
is that the model accepts image input.**

```powershell
# Example: switch to a Qwen vision model without touching the config file
$env:STUDY_WATCH_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:STUDY_WATCH_MODEL    = "qwen-vl-max"
$env:DASHSCOPE_API_KEY    = "sk-xxxx"
python monitor.py --check-api
```

> Whether `base_url` needs `/v1`: the code always appends `/chat/completions`. Services like
> OpenRouter, SiliconFlow and DashScope's compatible mode need `/v1`; `https://api.deepseek.com`
> does not. When unsure, just try it — a 404 means the path is wrong.

**Local models** (zero API cost, screenshots never leave the machine): start an OpenAI-compatible
server with llama.cpp or LM Studio, set `base_url` to `http://127.0.0.1:1234/v1`, and put any
non-empty string as the key.

Providers differ in how much of the protocol they support, so the client degrades **step by step**,
transparently to the rest of the code:

| Situation | Handling |
| --- | --- |
| `image_url.detail` rejected (llama.cpp / LM Studio / some gateways) | Retry without that field |
| `response_format: json_object` unsupported | Retry without it, relying on the tolerant JSON parser |
| Text returned inside a `content` array | Concatenated into a string |
| Auth failure / unknown model / rate limit | **No retry** — an actionable message including the current base_url and model |

---

## Cost

With `deepseek-flash`, one check costs roughly **$0.0006–0.0010** (400–700 input tokens for the image
plus 300–600 output tokens):

| Frequency | 4 hours/day | Per month (22 days) |
| --- | --- | --- |
| Every 2 minutes | 120 checks ≈ $0.10 | ≈ $2.2 |
| Every 3 minutes (default) | 80 checks ≈ $0.07 | ≈ $1.5 |
| Every 5 minutes | 48 checks ≈ $0.04 | ≈ $0.9 |

With a capture policy the real figure is lower: nothing is spent during games, chat and reading are
throttled, and only high-risk situations such as short-video feeds are checked more often.

Ways to spend less: raise the interval, drop `max_width` to 1280, keep `detail` at `low`, and use
capture rules to exclude irrelevant applications.

---

## Privacy

- Screenshots are **encoded in memory only** and sent straight to the API you configured; by default
  **nothing is written to disk** (`save_shots: false`)
- What does get written is the text verdict (what you were doing, plus the on-screen text quoted as
  evidence) — that evidence can contain fragments of what was on screen. If that bothers you, turn
  off `save_api_raw` or clear `data/` periodically
- The whole `data/` directory is in `.gitignore`; it holds logs, verdict records, raw replies, and
  any key saved from the panel (`data/secrets.json`)
- The dashboard listens on `127.0.0.1` only and is not exposed to the network
- To keep an application out of it entirely (password managers, private chats), give it
  `"action": "skip"` in `capture.rules`

---

## Tests

```powershell
.\selftest.bat        # runs all 17 checks and prints a summary
```

| Test | What it verifies |
| --- | --- |
| `tools/fix_script_encoding.py --check` | `.ps1` files have a UTF-8 BOM, `.cmd`/`.bat` files do not |
| `tools/check_readme.py` | Both READMEs: `**bold**` markers balanced (they may span lines), consistent table columns, fenced blocks closed, every table-of-contents anchor resolves |
| `tests/test_json_repair.py` | Malformed model JSON (unescaped quotes, missing/extra commas, prose around the object) can be repaired into something parseable |
| `tests/test_provider_compat.py` | Provider compatibility: the degradation chain for standard / no-`detail` / no-JSON-mode providers; auth and 404 failures don't retry and produce actionable messages |
| `tests/test_policy.py` | Capture policy: rule matching, the four skip/tick/polling/switch semantics, the safety gate, fallback when the policy is disabled |
| `tests/test_report.py` | Daily aggregation and duration conversion (including distracted, error and skipped records) |
| `tests/test_popup_shot.py` | The reminder window really renders its title/body/buttons (window contents captured via PrintWindow and checked structurally) |
| `tests/test_server.py` | The dashboard service starts, API fields are complete, timeline/category durations are consistent, start/stop control works |
| `tests/test_config_api.py` | Settings read/write: whitelist, type and value validation, whole-batch rejection of invalid input, keys returned masked only, config restored byte-for-byte afterwards |
| `tests/test_plan.py` | Pomodoro: phase advancement, long-break rule, round limit, resume across restart, and **breaks excluded from the focus rate**; the UI half is driven through a real headless browser |
| `tests/control_flow.py` | Control panel flow: start → pause → resume → stop, plus "pausing while stopped starts the monitor" |
| `tests/test_recovery.py` | Resilience: after the monitor is killed, a user action brings it back |
| `tests/test_intent.py` | User intent: after pressing stop, repeated status refreshes never resurrect the monitor |
| `tests/test_readonly_status.py` | The status endpoint is read-only: 40 rapid polls change no process counts, flags or `state.json` |
| `tests/test_cross_process_lock.py` | Cross-process start mutex: concurrent starts from independent processes produce exactly one monitor |
| `monitor.py --dry-run` | The screenshot and foreground-window pipeline works (no API call, no spend) |

`tests/test_plan_loop.py` is a **slow integration test** (~3 minutes, it genuinely waits for a phase
boundary), so it is not part of the one-shot suite. It starts a 1-minute-per-round plan plus a
background monitor, and verifies the monitor advances the phase by itself, logs the transition, and
tags break-period records as excluded from stats. Worth running after touching the pomodoro or
monitor-loop interfaces:

```powershell
python tests\test_plan_loop.py
```

`tools/` additionally holds diagnostics and generators:

| Tool | Purpose |
| --- | --- |
| `tools/status.py` | Print processes, today's summary and the tail of the log in one go |
| `tools/list_procs.py` | List service/monitor processes with start times (for hunting duplicates) |
| `tools/ensure_running.ps1` | Bring up both the service and monitoring from the command line |
| `tools/measure_capture.py` | Measure each screenshot stage's time and size |
| `tools/show_settings.py` | Print the currently effective settings |
| `tools/net_*.py` | Network diagnostics: latency/loss, real download throughput, CDN comparison |
| `tools/cdp_check.py` | Drive the real dashboard through a headless browser (timeline, date switching, whether hints survive a redraw) |
| `tools/cdp_eval.py` | Evaluate JS inside the real page and print the result (front-end debugging) |
| `tools/hunt_flaky.py` | Rerun the suite until an intermittent failure reproduces, keeping the context |
| `tools/repo_audit.py` | Pre-publish audit: scan for secrets, personal paths and stray runtime data |
| `tools/pack_source.py` / `pack_friend.py` | Build the source archive / a friendlier end-user archive |
| `tools/make_github_upload.py` | Produce a folder that can be dragged straight into GitHub's web uploader |
| `tools/make_readme_shots.py` | Take README screenshots automatically (start a real plan, capture the card and the full page) |
| `tools/make_demo_data.py` | Generate **privacy-free** demo data for screenshots; `--clean` removes it |
| `tools/make_shortcut*.ps1` | Rebuild the desktop shortcuts |
| `tools/fix_script_encoding.py` | Fix script encodings (see the development notes) |

---

## Known limits

- **Windows only**: it relies on `user32`/`gdi32`/`shcore`/`ntdll` (ctypes), `tkinter` and `winsound`
- **Exclusive-fullscreen games** may produce no capturable content and fall back to "idle/other"
- **Judgements can be wrong**: if it's too strict use `strictness: "loose"` or set
  `off_task_streak_required` to 2; if it's too lenient use `strict` and add `extra_rules`
- It only reminds you — **it does not lock the screen or block any application**
- It runs on another machine with no hard-coded paths, but needs Python 3.10+ and Pillow. The scripts
  look for Python in this order: `py-path.txt` in the project root (yours to create, gitignored) →
  common install locations (**preferring one that already has Pillow**) → `PATH`. On a machine with
  two Pythons, the one missing dependencies is skipped automatically
- Going cross-platform means rewriting `lib/winapi.py` (foreground window / idle / lock screen /
  DPI), `lib/notify.py` (the reminder window) and the screen-grab in `vision.py`. The policy layer,
  data layer, model layer and UI are platform-independent

---

## Repository layout

```
study-watch/
├─ monitor.py               entry point (equivalent to python -m lib.monitor)
├─ config.json              configuration (also editable in the dashboard)
├─ setup.ps1                one-shot setup: env checks, shortcuts, smoke test
├─ selftest.ps1 / .bat      one-shot test suite (17 checks)
├─ study-watch.cmd          target of the "study watch" desktop shortcut (pure ASCII wrapper)
├─ dashboard.bat / .ps1     target of the "dashboard" desktop shortcut
├─ start.ps1 / .bat         run in console mode
├─ pomodoro.ps1             pomodoro CLI (presets / custom / status / stop)
├─ start-25min.bat          double-click for one 25/5 round, then print the report
├─ report.bat / stop.bat    print the report / stop background monitoring
├─ requirements.txt         Pillow only
├─ LICENSE                  MIT
├─ assets/
│  ├─ study-watch.ico       multi-size icon (16–256, BMP/DIB frames)
│  ├─ icon-preview.png      size preview
│  ├─ pomodoro-card.png     focus-plan card used in this README
│  └─ dashboard-preview.png dashboard screenshot used in this README
├─ lib/
│  ├─ monitor.py            main loop and CLI
│  ├─ config.py             config loading and merging
│  ├─ vision.py             screenshot encoding, model calls, JSON parsing/repair, key resolution
│  ├─ policy.py             capture policy: decide whether this round needs a screenshot
│  ├─ plan.py               pomodoro state machine (phase advance / long break / resume)
│  ├─ winapi.py             foreground window / idle / lock screen / DPI (pure ctypes)
│  ├─ proc.py               process command-line lookup (pure ctypes, reads the PEB)
│  ├─ notify.py             topmost reminder window + sound + system-notification fallback
│  ├─ store.py / report.py  log I/O and daily aggregation
│  ├─ state.py              cross-restart state (last verdict time / last foreground app)
│  ├─ server.py             dashboard backend (stdlib HTTP + API + start/stop control)
│  ├─ icon.py               icon drawing and .ico generation
│  └─ common.ps1            shared PowerShell helpers
├─ web/
│  ├─ index.html            dashboard page (dark theme, no external dependencies)
│  └─ app.js                front end: timeline / donut / bars / lists / control / settings
├─ tests/                   17 self-tests
└─ tools/                   diagnostics and generators
```

---

## Development notes

Traps worth reading before changing code.

### Script encoding (the easiest one to hit)

- **`.ps1` must be saved as UTF-8 *with BOM***: PowerShell 5.1 only recognises UTF-8 via the BOM.
  Without it, non-ASCII comments are split as GBK bytes, quote pairing breaks, and you get a syntax
  error
- **`.cmd` / `.bat` must have *no* BOM**: cmd.exe reads the file as ANSI before `chcp` runs, and a
  leading BOM breaks `@echo off`
- **Don't put non-ASCII text in batch files**: those bytes can contain `0x5C` (backslash), which cmd
  treats as an escape and errors on. Keep UI text in `.ps1`

**This trap has been hit twice**: editing a `.ps1` with an ordinary text tool (or a script doing
`write_text(encoding="utf-8")`) silently drops the BOM, and the next run fails with a wall of
mojibake. So `fix_script_encoding.py` gained a `--check` mode, and it is now **the first step of the
test suite** — you don't have to remember to run it.

```powershell
python tools\fix_script_encoding.py          # fix automatically
python tools\fix_script_encoding.py --check  # check only (exits 1 when wrong)
```

### The icon

The `.ico` uses BMP/DIB frames rather than PNG frames. PNG frames are legal, but some Shell rendering
paths draw them as a blank page. Regenerate with `python -m lib.icon`.

### The status endpoint must stay read-only

The page polls `/api/data` every 5 seconds. Any "while I'm here, let me self-heal" change to that
path **breaks the stop button** (the monitor gets pulled back up seconds after you stop it).
`tests/test_readonly_status.py` guards this invariant.

### Starting needs a cross-process mutex

"User pressed start" and "the service self-heals" are two independent processes; they are serialised
by a file lock (`data/start.lock`). Without it you get two monitors: duplicate verdicts, duplicate
spend, two popups. `tests/test_cross_process_lock.py` guards this.

### Finding Python: pick the one that *works*

Two Pythons on one machine is normal (system plus a portable build). Sorting by path alone picks the
one **without Pillow** and the tool simply won't run. So `Resolve-Python` is ordered:

1. `py-path.txt` in the project root (explicit user choice, highest priority)
2. common install locations — **tried with `import PIL` first, preferring a working one**, and only
   then compared by version
3. `python` on `PATH`

Also: **never leave a path pointing at the author's machine** in a script — it is a silent time bomb
that only goes off on someone else's computer.

### Missing dependencies must be recoverable

`setup.ps1` had a trap: `$ErrorActionPreference = 'Stop'` treats the `ImportError` traceback a child
process writes to stderr as a terminating error, so the script dies — **precisely in the situation
new users hit most often**. The check has to relax it to `Continue` first.

When Pillow really is missing it installs automatically, and **falls back to a mirror when the
default index times out**. A direct PyPI connection is often unusable from mainland China, and this
step decides whether a new user can get set up at all.

### Git line endings and .ico

`core.autocrlf = true` is common on Windows. The repository root **must** contain a `.gitattributes`
stating:

```
*.cmd  text eol=crlf      # batch files must stay CRLF
*.ico  binary             # otherwise newline conversion corrupts the icon
*.png  binary
```

To verify: `git hash-object --path assets/study-watch.ico` must equal the `--no-filters` result
(381038 bytes, byte-identical, as measured here).

### Verify front-end changes in a real browser

Interactions like zooming and drag-selection **cannot be proven by a screenshot** — you can't tell
from a picture whether the state after a click is correct. And Edge's new headless mode does not
print anything for `--dump-dom`. The answer is CDP (Chrome DevTools Protocol): actually click and
actually read the DOM. `tools/cdp_check.py` exists for this, implementing WebSocket in **pure
standard library** with no packages installed. It is step 8 of the test suite, so a front-end change
that breaks interactions shows up immediately.

### Validation hints get wiped by the automatic redraw

The page redraws every 5 seconds. Any hint written straight into the DOM (an invalid-input warning,
say) disappears within 5 seconds and the user never sees it. The hint state has to be stored so the
redraw can prefer showing it.

### Don't screenshot real data for the README

The first attempt screenshotted the real dashboard, and the image carried chat-partner nicknames,
browsing history and what I was working on — all of which would have entered a public repository
alongside the README. So screenshots now use demo data from `tools/make_demo_data.py`:

```powershell
python tools\make_demo_data.py --days 3 --plan   # write demo records + one running plan
python tools\make_readme_shots.py                # start a plan, capture the card and full page
python tools\make_demo_data.py --clean           # remove the demo records
```

The demo data is **deterministically generated** (fixed seed), so screenshots come out identical
each time, which makes changes easy to compare. Back up `data/logs` before generating and restore it
afterwards: real and demo records are distinguishable via `demo: true`, but mixed together the
dashboard numbers stop looking like yours.

### Watch your quotes in demo copy

Use `「」` for quotes inside non-ASCII prose; do not nest ASCII `"` inside a double-quoted string —
it truncates the string and the error you get is "perhaps you forgot a comma", which points nowhere
useful. That one was hit four times in a single file.

---

## How this project was written

The code was written by the author pair-programming with AI assistants (Claude / DeepSeek Harness):
requirements, trade-offs and acceptance were the author's call, while much of the implementation,
debugging and testing leaned on AI. The test suite (17 checks, including driving the dashboard
through a headless browser) is the main reason that workflow holds up — it has blocked a good number
of changes that looked right and weren't.

See the [development notes](#development-notes) above for the traps found along the way.

## License

[MIT](LICENSE)
