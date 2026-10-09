# NOTICE —— 许可分层与署名

`LICENSE`（MIT）**只覆盖本项目的代码**。仓库里还带着第三方运行时与美术素材，
它们各自另有条款 —— 这就是这份 NOTICE 存在的原因。
（单独放一份而不是塞进 `LICENSE`，是为了让 GitHub 仍能正确识别出 MIT。）

`LICENSE` (MIT) **covers the code of this project only**. The repository also ships a
third-party runtime and artwork under their own terms — hence this NOTICE.

---

## 1. 代码 / Code

- **范围**：`monitor.py`、`lib/`、`web/`、`tools/`、`tests/`、各脚本
- **许可**：**MIT**（全文见 [`LICENSE`](LICENSE)）

## 2. Live2D 模型素材 / Live2D model artwork

- **范围**：`assets/live2d/**` —— `c_0120.moc3`、贴图 `c_0120.2048/*.png`、
  物理 `c_0120.physics3.json`、动作 `motions/*.motion3.json`、
  表情 `expressions/*.exp3.json`
- **许可**：**[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh)**
  （署名 — **非商业性使用** — 相同方式共享）
- **署名（三位，缺一不可）**：见下方「角色版权链」
- **来源**：模型作者无偿分享的 VTube Studio 模型包《DS鲸鱼娘》，
  原《使用须知》原文见 [`PROVENANCE.md`](PROVENANCE.md)

`c_0120.model3.json` 由本项目生成（`tools/build_live2d_model.py`）——
原包靠文件名加载动作，没有 `model3.json`，这里把动作与表情注册成标准条目，
**只是格式转换，不产生新的权利**。

## 3. 运行时 / Runtime

| 组件 | 文件 | 许可 | 版权 |
| --- | --- | --- | --- |
| Live2D Cubism Core 5.1.0 | `assets/vendor/live2dcubismcore.min.js` | **Live2D 专有许可**（Cubism SDK 的 "Redistributable Code"） | Live2D Inc. |
| PIXI.js 6.5.10 | `assets/vendor/pixi.min.js` | MIT | PIXI.js contributors |
| pixi-live2d-display 0.4.0 | `assets/vendor/cubism4.min.js` | MIT | pixi-live2d-display contributors |

## 4. 本项目是非商业的 / Non-commercial

本项目**完全免费**：不收费、不带货、不接广告变现、不卖周边、
不作为任何付费产品或服务的卖点。

模型作者的无偿分享**不解除**角色形象本身的 NC 条件。
如果你要把本项目用于商业目的，**必须先移除 `assets/live2d/` 与
`assets/reminder/` 下的角色素材**，否则违反 CC BY-NC-SA 4.0。

---

有任何权利主张，请开一个 [Issue](https://github.com/lgbabb/study-watch/issues)。

## 另：提醒卡片里的角色立绘

`assets/reminder/**`、`assets/_reminder_src/**` 以及 README 里用到的角色配图，
与 Live2D 模型**同源同版权**（同一角色的不同表现），适用同样的
CC BY-NC-SA 4.0 条款与同一份三位署名。
