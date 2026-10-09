# 为什么不走"预渲染帧"方案（决策记录）

桌宠现在是**浏览器 app 模式的无边框窗口**（`lib/pet_window.py` + `web/pet.html`）。
下面这份记录是为了避免以后有人（包括我自己）再花时间重走一遍已经量过的路。

## 当时的诉求

> 能不能不依赖网页？

## 硬约束

Live2D 的 `.moc3` 必须由 **Cubism 运行时**（WebGL / 原生 OpenGL）渲染，
**Python 侧没有可用的 Cubism 绑定**。所以只有两条路：

| 路线 | 做法 | 结果 |
| --- | --- | --- |
| 运行时渲染 | Python 里直接画 Live2D | **不可能**（没有绑定） |
| 构建期预渲染 | 浏览器烘成帧，Python 播放 | 可行，见下 |

## 已实测的能力（结论：可行）

**1. 逐像素透明窗口**（`tools/probe_layered_window.py`）

这是原先不得不走浏览器的**唯一**原因：tkinter 的窗口不能做逐像素 alpha，
透明像素会显示成它自己的 RGB。

用 Windows 原生的 `UpdateLayeredWindow` 可以做到，纯 ctypes + Pillow：

```python
CreateWindowExW(WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW, ...)
CreateDIBSection(...)                      # 填 BGRA
UpdateLayeredWindow(hwnd, ..., AC_SRC_ALPHA)
```

实测返回 1；截屏核验窗口四角透出的是桌面颜色、抗锯齿边缘是渐隐的。

**2. 资产体积**（真渲染 380x480 @20fps）

| 格式 | 单帧 | 120 帧 | 200 帧 | 300 帧 |
| --- | --- | --- | --- | --- |
| PNG | 101 KB | 11.8 MB | 20 MB | 30 MB |
| **WebP(q82)** | **18 KB** | **2.1 MB** | **3.5 MB** | **5.3 MB** |

画质核验：WebP(q82) 与 PNG 在 380x480 下肉眼无差别（平均像素差 1.76）。

**3. 播放性能**（`tools/probe_frame_playback.py`）

```
解码 + 转 BGRA     中位  9.38 ms（一次性，可预解码）
UpdateLayeredWindow 中位  0.55 ms
连续播放单帧        中位  0.47 ms｜实测 19.6 fps（预算 50 ms/帧）
```

## 成本对比

| | 浏览器窗口（**现用**） | 预渲染帧 |
| --- | --- | --- |
| 常驻内存 | 800–1000 MB（一个 Edge 进程） | 83 MB（120 帧全解码）<br>约 30 MB（滚动缓存） |
| 磁盘 | 4.7 MB | 2.1 MB |
| 依赖 | Edge | **无** |
| 动作 / 表情 | **8 动作 + 15 表情，实时任意组合** | 固定几段预渲染 |
| 实时交互（鼠标跟随等） | 可以 | 做不到 |
| 构建步骤 | 无 | 需烘一次帧（120 帧约 4 秒） |

## 决定

**用浏览器窗口**。理由是"动作可实时组合 + 实时交互"这两点，
是桌宠好玩的关键；而内存代价用户可以接受（几百 MB 以内）。

预渲染帧这条路**技术上完全可行**，只是取舍上不划算。如果以后要求
"零依赖、低内存"优先于"动作丰富"，按上面的数字可以直接开工：
`tools/probe_layered_window.py`（窗口）与
`tools/probe_frame_playback.py`（播放）已经把两个关键环节都验证过了。

## 踩过的坑（别重犯）

- **`PrintWindow` 抓不到 Chromium 的 WebGL 内容**。桌宠窗口体检必须走
  CDP 的 `Page.captureScreenshot`（走合成器），否则会把好窗口判成坏的。
  `tools/check_pet_window.py` 已经用的是 CDP。
- **`model.width` 返回的是"应用缩放后的显示宽度"**（345.94），不是模型
  单位尺寸（4068）。拿它当缩放分母会算出 `scale=1`，角色被放成几百倍。
  要用 `model.getBounds()` 实测未缩放时的占用再反推。
- **`--window-size` 不可靠**：请求 320x400 时页面视口只有 215x332。
  窗口起来后用 Win32 `SetWindowPos` 定精确尺寸，页面用 ResizeObserver 跟随。
- **ctypes 的 WNDPROC**：参数与返回值必须显式声明类型，否则 64 位下
  lParam 被当 int32、指针一大就抛 `OverflowError`；`DefWindowProcW` 的
  restype 要用 `c_void_p`（LRESULT 是指针宽度）。
