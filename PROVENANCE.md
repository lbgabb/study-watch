# PROVENANCE —— 素材来源与许可范围

一句话：**代码随便用（MIT）；角色素材非商业**（CC BY-NC-SA 4.0），
署名要写全三位：**上善无形 / ZipZipPipe / 氵六青**。

---

## 一、许可范围

| 范围 | 许可 |
| --- | --- |
| `lib/`、`web/`、`tools/`、`tests/`、`monitor.py`、各脚本与文档 | **MIT** |
| `assets/live2d/**`（moc3 / 贴图 / 物理 / 动作 / 表情） | **非商业**，CC BY-NC-SA 4.0 |
| `assets/reminder/**`、`assets/_reminder_src/**`（提醒卡片立绘） | **非商业**，CC BY-NC-SA 4.0 |
| `assets/vendor/live2dcubismcore.min.js` | **Live2D 专有许可**（可再分发代码） |
| `assets/vendor/pixi.min.js`、`cubism4.min.js` | MIT |

## 二、角色版权链（三重，必须都署名）

这个形象是三段创作叠起来的，所以署名不能只写一位：

| 版权所有人 | 贡献 | 主页 |
| --- | --- | --- |
| **上善无形** | 鲸鱼娘角色形象原作，原创 OC「溟月」 | <https://space.bilibili.com/4456176> |
| **ZipZipPipe** | 加入 DeepSeek 元素的「女仆鲸鱼娘」二次设计 | <https://space.bilibili.com/4168597> |
| **氵六青** | Live2D 化：绑定、动作、表情（B站 UID 11272072） | <https://space.bilibili.com/11272072> |

形象链：上善无形「溟月」→ ZipZipPipe 女仆鲸鱼娘 → 氵六青 Live2D 化。

## 三、逐项来源

| 文件 | 来源 / 说明 |
| --- | --- |
| `assets/live2d/c_0120.moc3`、`c_0120.2048/texture_*.png`、`c_0120.physics3.json`、`c_0120.cdi3.json`、`motions/*.motion3.json`、`expressions/*.exp3.json` | 来自模型作者分享的《DS鲸鱼娘》模型包（原作者 B 站 **@氵六青**） |
| `assets/live2d/c_0120.model3.json` | **本项目生成**（`tools/build_live2d_model.py`）。原包是 VTube Studio 用，靠文件名加载动作，没有 model3.json；这里把 8 个动作与 15 个表情注册成标准条目，便于 Web 端渲染器加载 |
| `assets/vendor/live2dcubismcore.min.js` | Live2D 官方 CDN `https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js`（207,155 字节，保留原始许可头） |
| `assets/vendor/pixi.min.js` | npm `pixi.js@6.5.10` |
| `assets/vendor/cubism4.min.js` | npm `pixi-live2d-display@0.4.0` |
| `assets/reminder/**`、`assets/_reminder_src/**` | 同一角色形象的静态立绘，由使用者自行整理为提醒卡片 |

## 四、模型作者的使用须知（原文照录）

```
商用直播√
自印物料√

禁止任何形式的盗用以及出售，此模型为无偿分享，NC条款禁止"以商业利益为主要目的"的行为

模型制作：B站@氵六青（11272072）
使用问题和定制桌宠请加QQ交流群：645169617
————————————————————————————————————————————
形象版权所有@上善无形 与 @ZipZipPin
本作品采用 CC BY-NC-SA 4.0 协议进行许可。
协议链接：https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh
```

也就是说：**允许**非商业的自定义桌宠改造与分享，**禁止**盗用与出售。
本项目按此范围使用，**不额外授予任何权利**。

## 五、如果你是权利人

认为本项目对素材的使用超出了上述范围，请开
[Issue](https://github.com/lgbabb/study-watch/issues) 说明，
会立即下架相关素材。
