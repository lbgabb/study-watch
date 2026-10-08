# 学习监督助手（study-watch）

> 每隔几分钟截一张屏，交给视觉模型判断"你此刻在做什么"。分心就弹窗提醒，并把每次判定记成可复盘的时间轴与日报。

判定不是靠窗口标题猜的——**截图会真的送进模型**，所以"标题写着高数课、实际在刷短视频"这种情况也能识别出来。

```
[00:10:23] 截图 1440x900 -> 1440x900 / 167 KB｜前台：msedge.exe
[00:10:25] 在状态｜学习｜在 B 站观看理论力学期末急救课程，画面正讲转动惯量的平行轴定理
[00:10:25]     依据：播放区是课程讲义，"02 转动惯量——平行轴定理"，公式 J_z = J_zc + md²
[00:10:25]     2.5s 内返回｜tokens 684/347｜$0.0006
```

- **Windows 桌面工具**，Python 3.10+，唯一第三方依赖是 Pillow
- **不绑定 DeepSeek**：走标准 OpenAI 兼容协议，任何支持图片输入的模型都能用（含本地 llama.cpp / LM Studio）
- **按前台应用分配截图**：游戏不判定、短视频一切换就查、聊天每 10 分钟、阅读每 5 分钟……省调用也提准确率
- **本地网页仪表盘**：时间轴、类别占比、近 7 天、分心明细，启停与全部设置都在这里改
- 截图默认**只在内存里**编码后发 API，不落盘

![仪表盘](assets/dashboard-preview.png)

---

## 目录

- [快速开始](#快速开始)
- [截图策略：按前台应用分配](#截图策略按前台应用分配)
- [可视化仪表盘](#可视化仪表盘)
- [判断机制](#判断机制)
- [配置](#配置)
- [换别的 API / 本地模型](#换别的-api--本地模型)
- [成本](#成本)
- [隐私说明](#隐私说明)
- [自测](#自测)
- [已知边界](#已知边界)
- [目录结构](#目录结构)
- [开发笔记](#开发笔记)

---

## 快速开始

### 一键部署（推荐）

```powershell
git clone <你的仓库地址> study-watch
cd study-watch
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` 会依次：查 Windows → 找 Python → 检查 `PIL`/`tkinter`/`winsound` → 检查 API key → 缺图标就生成 → 建两个桌面快捷方式 → 跑一次**不花钱**的冒烟测试。

### 手动

```powershell
python -m pip install -r requirements.txt          # 只有 Pillow
$env:DEEPSEEK_API_KEY = "sk-xxxx"                  # 或者写进 ~/.dsh/.credentials.yaml
python monitor.py --check-api                      # 先确认模型能用
python monitor.py --minutes 25                     # 监督 25 分钟试试
```

### 日常使用

| 入口 | 作用 |
| --- | --- |
| 桌面快捷方式 **学习监督** | 双击静默转入后台开始监督，已在运行则不会重复启动 |
| 桌面快捷方式 **学习监督 仪表盘** | 打开网页仪表盘（`http://127.0.0.1:8770/`） |
| `stop.bat` | 结束后台监督 |
| `report.bat` | 打印今日日报 |

常用命令：

```powershell
python monitor.py --status       # 体检：进程、服务、配置是否生效、今日数据
python monitor.py --policy       # 看当前前台应用会命中哪条截图规则
python monitor.py --check-api    # 用内置小图自检模型连通性（不截你的屏）
python monitor.py --once         # 立刻判一次
python monitor.py --report --days 7
python monitor.py --export       # 导出 Markdown 日报
```

---

## 截图策略：按前台应用分配

同一套间隔用在所有程序上是浪费——看视频、聊天、写代码的"变化速度"完全不同。规则写在 `config.json` 的 `capture.rules`，**按书写顺序，第一条命中者生效**：

```jsonc
"capture": {
  "enabled": true,
  "min_gap_sec": 20,       // 兜底闸门：两次判定至少隔这么久（防止重启后连打）
  "rules": [
    // 这个应用干脆不判定（游戏、模拟器）
    { "name": "游戏与模拟器", "process": ["steam", "mumup*", "pcl*", "minecraft*"],
      "action": "skip" },

    // 一切换到它就立刻查（切换点最容易漏判）
    { "name": "短视频", "title_contains": ["抖音", "快手", "小红书"],
      "switch_check": true },

    // 长时间停在一个窗口的：切过来先看一眼，之后每 10 分钟一次
    { "name": "即时通讯", "process": ["wechat*", "qq", "tim*", "discord*"],
      "polling_sec": 600 },

    // 滚动阅读的：距上次判定满 N 秒才查
    { "name": "长文阅读", "process": ["sumatrapdf*", "winword*", "wps*"],
      "tick_sec": 300 }
  ]
}
```

| 字段 | 作用 |
| --- | --- |
| `process` / `process_contains` | 按进程名匹配，支持 `*` 通配 |
| `title` / `title_contains` | 按窗口标题匹配（与进程命中任一即可） |
| `action: "skip"` | 该应用**不判定**：不截图、不调 API、不计入统计 |
| `tick_sec: N` | 距上次判定满 N 秒才查 |
| `polling_sec: N` | 切到该应用先查一次，之后每 N 秒一次 |
| `switch_check: true` | 窗口一切换到该应用就立刻查 |

没命中任何规则的程序走全局 `interval_sec`——**不配规则时行为和朴素版本完全一样**。

跳过的原因会写进日志，每次监督结束也会汇总：

```
该应用不判定：notepad（规则：记事本不判定），本轮不截图
本次监督结束：运行 40秒｜判定 0 次｜按应用策略省下 4 次判定｜花费 $0.0000
```

状态存在 `data/state.json`，**跨重启续上**，所以重启监督不会连打好几次。

---

## 可视化仪表盘

浏览器打开 `http://127.0.0.1:8770/`（端口被占会自动往后找）。

| 区域 | 内容 |
| --- | --- |
| 概览卡 | 当天专注率、覆盖时长、分心次数、花费 |
| **现在 / 当天最后一条** | 最近一次判定的"在做什么" + 判断依据（屏幕上看到的原文） |
| **时间轴** | 按类别着色的横条，上行=在状态、下行=分心，**条长就是真实时长**；可缩放、可选日期 |
| **分心记录明细** | 什么时候分心的、当时在做什么、依据是什么；可跟随时间轴区间 |
| 类别占比 / 近 7 天 / 分心来源 / 运行概况 | 环形图、堆叠柱状图、按程序排名、token 与成本 |
| **控制面板** | 开始 / 暂停 / 停止 / 立即判一次 / 导出 / 打开设置 |

### 时间轴：缩放与自定义区间

时间轴默认铺满当天，想细看某一段有四种操作：

| 操作 | 效果 |
| --- | --- |
| **日期下拉**（左上） | 切换要看的日期（列出所有有记录的日子）；`?day=2026-10-08` 也能直接打开某天，可收藏 |
| **预设按钮** | 全天 / 最近 1·3·6·12 小时。看今天时以"现在"为锚点，看历史日期时以**那天末尾**为锚点 |
| **自定义区间** | 填起止时间（HH:MM）后点「应用」；起 > 止时自动按跨零点处理（如 22:00 → 02:00） |
| **在时间轴上拖选** | 直接框住一段就缩放过去；**滚轮**以光标位置为中心缩放 |
| 重置 | 回到全天视图 |

细节：

- 刻度间隔**自适应**：全天时按小时，放大到小时以内会自动变成 10 分钟、5 分钟
- 只看今天时会画一条"现在"的虚线做参照
- 标题实时显示当前窗口与段数，例如 `23:35–00:01｜12 段`
- 「分心记录」可以勾选**跟随时间轴区间**，只看这段时间里的分心
- 看历史日期时，顶部会标明"当天最后一条 YYYY-MM-DD（历史）"，概览卡也换成那天的数字（近 7 天图始终按当前情况显示）

### 控制面板的三种状态

| 状态 | 含义 | 可做的操作 |
| --- | --- | --- |
| 未在监督 | 没有监督进程 | 开始监督 |
| 监督中 | 每 N 秒截屏判定一次 | 暂停判定、停止监督、立即判一次、导出、打开设置 |
| 已暂停 | 进程还在待命，**不截图、不花钱**，恢复是瞬时的 | 继续监督、停止监督、打开设置 |

「暂停」只是不再判定，进程留着；「停止」是彻底结束监督进程。
服务会**尊重你的意图**：点过停止之后，即使监控进程被外部杀掉，也不会被状态刷新偷偷拉回来。

### 设置都在控制面板里

控制面板的「打开设置」滑出抽屉，**不用手编 config.json**：

| 分组 | 能改什么 | 生效时机 |
| --- | --- | --- |
| API key | 查看现状（只显示掩码 + 来源），填新的并保存 | 立即 |
| 判定节奏 | 判定间隔、空闲跳过阈值、最小间隔、全局间隔覆盖 | 下一轮判定 |
| 截屏与图片 | 图片精度、JPEG 质量、缩放宽度、是否落盘、是否存原始回复 | 多数下一轮 |
| 判定标准 | 学习目标、严格程度、额外规则、归类约定 | 下一轮判定 |
| 提醒 | 开关、提示音、安静时长、连续几次才提醒、自动关闭 | 下一轮判定 |
| API / 模型 | base_url、模型名、key 环境变量名、凭据文件、超时、max_tokens、temperature | **需重启监督** |

每个字段旁有徽章标明「下一轮生效」还是「需重启」——监控进程**每一轮都重读配置文件**，所以大部分设置改完下个周期就生效，不必重启。

- **测试 API 连通**：用一张内置小图（**不截你的屏**）验证 base_url / 模型 / key，不落盘
- **保存**：只写 `config.json`；有非法值时**整批拒绝**并说明原因
- key 存到 `data/secrets.json`（不进版本库）。优先级：环境变量 > 面板保存 > 凭据文件
- 想直接打开设置页：`http://127.0.0.1:8770/?settings=1`

---

## 判断机制

一轮的完整流程：

```
循环开始
 ├─ 重读配置（面板改的设置从这里生效）
 ├─ 检查 data/paused        → 暂停中：本轮不做任何事
 ├─ 检查是否锁屏 / 空闲过长  → 是：跳过本轮（不截图、不花钱、不计入统计）
 ├─ 按前台应用决定要不要截图 → 策略说不查：跳过
 ├─ 截图（整个虚拟桌面）→ 缩放 → JPEG → base64
 ├─ 连"前台程序名 + 窗口标题"发给视觉模型
 ├─ 解析 JSON 判定 → 写日志 → 分心则弹提醒
 └─ 睡满 interval_sec → 回到循环开始
```

模型被要求只回一个 JSON：

```json
{"activity":"一句话描述此刻在做什么","category":"学习|工作|娱乐|社交|游戏|购物|闲置|其他",
 "on_task":true,"confidence":0.86,"basis":"引用屏幕上实际看到的具体文字或界面元素"}
```

提示词里写死了几条关键规则（可在设置里改）：

- **以画面为准**，窗口标题只是线索，防止"标题像学习、内容是短视频"漏判
- 短视频/推荐流形态（一屏一视频、弹幕、点赞投币）**即使内容是知识科普也算娱乐**
- 课程视频、教材 PDF、题库、写代码、背单词、记笔记算学习
- 锁屏 / 纯桌面 / 看不出在用电脑算"闲置"

模型偶尔会吐出不合法 JSON，此时会**宽容修补**（漏转义引号、缺/多逗号、夹带解释文字），仍失败就带上"必须输出合法 JSON"的提示重发一次。

截屏开销（2880×1800 屏实测）：抓屏 ~98ms + 缩放 ~80ms + 编码 ~15ms ≈ **193ms**，JPEG 约 150KB。

---

## 配置

配置文件 `config.json`（也可以在仪表盘里改）：

```jsonc
{
  "interval_sec": 180,        // 判定间隔（秒）
  "idle_skip_sec": 300,       // 超过这么久没键鼠输入就跳过
  "max_width": 1600,          // 截图缩放宽度，越小越省
  "detail": "low",            // 图片精度：low 更省，high 能看清小字
  "capture": { /* 见上文"截图策略" */ },
  "api": {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key_env": "DEEPSEEK_API_KEY",
    "credentials_file": "~/.dsh/.credentials.yaml"
  },
  "judge": {
    "goal": "备考学习（课程视频、教材、网课、题库、编程/外语学习、写作业与笔记）",
    "strictness": "normal",   // loose 宽松 / normal / strict 严格
    "extra_rules": [],
    "alias_rules": []
  },
  "reminder": {
    "enabled": true, "sound": true,
    "mute_after_remind_sec": 300,
    "off_task_streak_required": 1,   // 改成 2 就是"连续 2 次分心才提醒"
    "auto_close_sec": 60
  },
  "privacy": {
    "save_shots": false,      // true 会把截图存到 data/shots
    "save_api_raw": true      // 存模型原始回复，方便排查误判
  }
}
```

环境变量可临时覆盖：`STUDY_WATCH_INTERVAL`、`STUDY_WATCH_MODEL`、`STUDY_WATCH_BASE_URL`、`DEEPSEEK_API_KEY`。

---

## 换别的 API / 本地模型

用的是**标准 OpenAI 兼容协议**（`POST {base_url}/chat/completions`，Bearer 鉴权，图片走 `image_url` 的 base64 data URL），不是某家的私有接口。**唯一要求是模型支持图片输入。**

```powershell
# 例：换成通义千问兼容模式（不用改配置文件）
$env:STUDY_WATCH_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:STUDY_WATCH_MODEL    = "qwen-vl-max"
$env:DASHSCOPE_API_KEY    = "sk-xxxx"
python monitor.py --check-api
```

> `base_url` 要不要带 `/v1`：代码统一拼 `{base_url}/chat/completions`。OpenRouter、SiliconFlow、通义兼容模式这类要写 `/v1`；`https://api.deepseek.com` 这类不用。拿不准就试一次——404 就是路径不对。

**本地模型**（零 API 费用、截图不出本机）：llama.cpp 或 LM Studio 起了 OpenAI 兼容服务后，`base_url` 填 `http://127.0.0.1:1234/v1`，key 随便填个非空值。

不同服务商对协议的支持程度不一样，代码里做了**逐级降级**（对上层透明）：

| 情况 | 处理 |
| --- | --- |
| 不认 `image_url.detail`（llama.cpp / LM Studio / 部分网关） | 自动去掉该字段重发 |
| 不支持 `response_format: json_object` | 自动去掉它重发，靠宽容 JSON 解析兜底 |
| 正文放在 `content` 数组里 | 自动拼接取文本 |
| 鉴权失败 / 模型不存在 / 被限流 | **不重试**，直接给出可操作提示（含当前 base_url 与 model） |

---

## 成本

以 `deepseek-flash` 为例，每次判定约 **$0.0006~0.0010**（图 400~700 输入 token + 300~600 输出）：

| 频率 | 每天 4 小时 | 每月（22 天） |
| --- | --- | --- |
| 2 分钟一次 | 120 次 ≈ $0.10 | ≈ $2.2 |
| 3 分钟一次（默认） | 80 次 ≈ $0.07 | ≈ $1.5 |
| 5 分钟一次 | 48 次 ≈ $0.04 | ≈ $0.9 |

配上截图策略后实际更低：游戏时段完全不查，聊天/阅读时段降频，只有短视频这类高风险场景才提高频率。

省钱手段：调大间隔、把 `max_width` 降到 1280、`detail` 保持 `low`、用截图策略把无关程序排除掉。

---

## 隐私说明

- 截图**只在内存里**编码后直接发给你配置的 API，默认**不落盘**（`save_shots: false`）
- 落盘的是文本判定结果（在做什么、依据里引用的屏幕文字）——依据可能包含屏幕上的原文片段。介意的话关掉 `save_api_raw`，或定期清理 `data/`
- `data/` 整个目录已在 `.gitignore` 里，包含日志、判定记录、原始回复、以及面板里填的 key（`data/secrets.json`）
- 仪表盘只监听 `127.0.0.1`，不对外暴露
- 想让它别看某个应用（密码管理器、私密聊天），在 `capture.rules` 里给它 `"action": "skip"`

---

## 自测

```powershell
.\selftest.bat        # 一键跑全部 13 项，最后给出汇总
```

| 测试 | 验证什么 |
| --- | --- |
| `tests/test_json_repair.py` | 模型吐出畸形 JSON（漏转义引号、缺逗号、多余逗号、夹带解释文字）能否修补回可解析 |
| `tests/test_provider_compat.py` | 服务商兼容性：标准 / 不认 detail / 不支持 JSON 模式的降级链；鉴权与 404 不重试且提示可操作 |
| `tests/test_policy.py` | 截图策略：规则匹配、skip/tick/polling/switch 四种语义、兜底闸门、关闭策略时的回退 |
| `tests/test_report.py` | 日报聚合与时长折算（含分心、错误、跳过三类记录） |
| `tests/test_popup_shot.py` | 提醒窗是否真的渲染出标题/正文/按钮文字（PrintWindow 抓窗口内容做结构判定） |
| `tests/test_server.py` | 仪表盘服务能否启动、API 字段是否齐全、时间轴/类别时长是否自洽、启停控制是否生效 |
| `tests/test_config_api.py` | 设置读写：白名单、类型/取值校验、非法输入整批拒绝、key 只回掩码、跑完配置逐字节还原 |
| `tests/control_flow.py` | 控制面板流程：开 → 暂停 → 恢复 → 停止，以及"没在跑时点暂停会自动拉起" |
| `tests/test_recovery.py` | 服务韧性：监控进程被强杀后，用户主动操作能把监控接回来 |
| `tests/test_intent.py` | 用户意图：点过停止之后，反复刷新状态也不会把监控偷偷拉起来 |
| `tests/test_readonly_status.py` | 状态接口只读性：连打 40 次轮询，进程数/标记/state.json 零变化 |
| `tests/test_cross_process_lock.py` | 跨进程启动互斥：多个独立进程并发启动只起一个监控 |
| `tools/cdp_check.py` | **仪表盘界面交互**（无头 Edge + CDP 实测）：时间轴预设/自定义区间/拖选缩放、提示不被自动重绘冲掉、日期切换与历史标注 |
| `monitor.py --dry-run` | 截图与前台窗口采集链路是否正常（不调用 API、不花钱） |

另外 `tools/` 下有排障与生成工具：

| 工具 | 作用 |
| --- | --- |
| `tools/status.py` | 一次打印进程、今日汇总、日志尾部 |
| `tools/list_procs.py` | 列出服务/监控进程及启动时间（排查重复进程） |
| `tools/ensure_running.ps1` | 命令行把服务与监督都拉起来（排障用） |
| `tools/measure_capture.py` | 实测截屏各阶段耗时与体积 |
| `tools/show_settings.py` | 打印当前生效的设置 |
| `tools/net_*.py` | 网络诊断：延迟/丢包、真实下载吞吐、CDN 节点对比、可选清晰度 |
| `tools/cdp_check.py` | 无头浏览器实测仪表盘交互（时间轴、设置抽屉、日期切换） |
| `tools/cdp_eval.py` | 在真实页面里执行 JS 并打印结果（前端排障用） |
| `tools/repo_audit.py` | 发布前审计：扫描密钥、个人路径、不该提交的运行数据 |
| `tools/pack_source.py` / `pack_friend.py` | 打包源码包 / 给朋友的运行包 |
| `tools/make_github_upload.py` | 生成可直接拖到 GitHub 网页上传的目录 |
| `tools/make_shortcut*.ps1` | 重建桌面快捷方式 |
| `tools/fix_script_encoding.py` | 修正脚本编码（见下方开发笔记） |
| `tools/prepublish_audit.py` | 发布前扫描密钥与硬编码路径 |

---

## 已知边界

- **只在 Windows 上跑**：依赖 `user32`/`gdi32`/`shcore`/`ntdll`（ctypes）、`tkinter`、`winsound`
- **全屏独占的游戏**可能截不到内容，会落到"闲置/其他"
- **判定会误判**：觉得太严就用 `strictness: "loose"`，或把 `off_task_streak_required` 改成 2；觉得太松就 `strict` 并加 `extra_rules`
- 它只提醒，**不锁屏、不阻止你打开任何程序**
- 换机器可用（无硬编码路径），但需要装 Python 3.10+ 与 Pillow；`tools/*.ps1` 顶部的 Python 候选路径第一项指向作者环境，有 `python` 在 PATH 就无所谓
- 想跨平台需要重写 `lib/winapi.py`（窗口/空闲/锁屏/DPI）、`lib/notify.py`（提醒窗）、以及 `vision.py` 里的抓屏方式；策略层、数据层、模型层、界面都是平台无关的

---

## 目录结构

```
study-watch/
├─ monitor.py               入口（等价 python -m lib.monitor）
├─ config.json              配置（也可在仪表盘里改）
├─ setup.ps1                一键部署：查环境、建快捷方式、冒烟测试
├─ selftest.ps1 / .bat      一键自测（13 项）
├─ study-watch.cmd          桌面「学习监督」快捷方式的目标（纯 ASCII 外壳）
├─ dashboard.bat / .ps1     桌面「学习监督 仪表盘」快捷方式的目标
├─ start.ps1 / .bat         控制台模式运行
├─ start-25min.bat          番茄钟模式（25 分钟后自动结束并出日报）
├─ report.bat / stop.bat    看日报 / 结束后台监督
├─ requirements.txt         只有 Pillow
├─ LICENSE                  MIT
├─ assets/
│  ├─ study-watch.ico       多尺寸图标（16~256，BMP/DIB 帧）
│  ├─ icon-preview.png      各尺寸预览
│  └─ dashboard-preview.png README 用的界面截图
├─ lib/
│  ├─ monitor.py            主循环与 CLI
│  ├─ config.py             配置加载与合并
│  ├─ vision.py             截图编码、调用模型、JSON 解析与修补、key 解析
│  ├─ policy.py             截图策略：按前台应用决定这一轮要不要截图
│  ├─ winapi.py             前台窗口 / 空闲 / 锁屏 / DPI（纯 ctypes）
│  ├─ proc.py               进程命令行查询（纯 ctypes 读 PEB）
│  ├─ notify.py             置顶提醒窗 + 提示音 + 系统通知回退
│  ├─ store.py / report.py  日志读写与日报聚合
│  ├─ state.py              跨重启状态（上次判定时间 / 上次前台应用）
│  ├─ server.py             仪表盘后端（纯标准库 HTTP + API + 启停控制）
│  ├─ icon.py               图标绘制与 .ico 生成
│  └─ common.ps1            PowerShell 侧公共函数
├─ web/
│  ├─ index.html            仪表盘页面（深色主题，无外部依赖）
│  └─ app.js                前端：时间轴 / 环形图 / 柱状图 / 明细 / 控制 / 设置
├─ tests/                   13 项自测
└─ tools/                   排障与生成工具
```

---

## 开发笔记

几个踩过的坑，改代码前值得看一眼。

### 脚本编码（最容易踩）

- **`.ps1` 必须存成 UTF-8 with BOM**：PowerShell 5.1 靠 BOM 才认 UTF-8，否则中文注释会被按 GBK 拆字节，连引号配对都被破坏、直接语法报错
- **`.cmd` / `.bat` 必须不能有 BOM**：cmd.exe 在 `chcp` 之前就按 ANSI 读文件，行首 BOM 会让 `@echo off` 失效
- **批处理里不要写中文**：中文字节里可能含 `0x5C`（反斜杠），cmd 会把它当转义而报错。UI 文案一律交给 `.ps1`

改完跑一次 `python tools/fix_script_encoding.py` 自动修正。

### 图标

`.ico` 用了 BMP/DIB 帧而不是 PNG 帧。PNG 帧在规范允许，但部分 Shell 渲染路径会显示成白纸。重新生成：`python -m lib.icon`。

### 状态接口必须只读

页面每 5 秒轮询 `/api/data`。任何"顺手在这里自愈一下"的改动都会让**停止按钮失效**（点完几秒又被拉起来）。`tests/test_readonly_status.py` 专门守这条不变量。

### 启动要跨进程互斥

"用户点开始"和"服务自愈"是两个独立进程，靠文件锁（`data/start.lock`）串行化，否则会起出两个监控进程——重复判定、重复扣费、提醒弹两次。`tests/test_cross_process_lock.py` 守这条。

---

## License

[MIT](LICENSE)
