---
name: vnc-browser-launcher
description: 在沙箱 VNC 远程桌面上启动可见的浏览器窗口
triggers:
  - 在 VNC 上打开浏览器
  - 看到浏览器 UI
  - Playwright 有头模式显示
---

# VNC 浏览器启动器

在沙箱远程桌面 (VNC/KasmVNC) 上启动可见的浏览器窗口。

## 触发场景

- 用户要求"看到浏览器 UI"
- 需要在 VNC 桌面上显示网页
- Playwright 无头模式截图不够用，需要真实的浏览器窗口

## 核心问题

### 问题 1: xvfb-run 虚拟显示隔离

- `xvfb-run` 创建独立的虚拟 X 服务器 (:99 或动态分配)
- 浏览器显示在 xvfb-run 的虚拟显示上，**不在 VNC 的桌面 :1 上**
- 用户在 VNC 桌面上看不到浏览器

### 问题 2: X Authority 授权问题

VNC 服务器使用 `/root/.Xauthority` 进行授权，但：
- 直接运行 `xauth` 命令会连不上 X 服务器
- 需要通过 `XAUTHORITY=/root/.Xauthority` 环境变量访问

### 问题 3: Playwright Firefox 包装脚本

- `/usr/local/bin/firefox` 是 Playwright 的包装脚本
- 不支持 `headless=False` 显示在真实 X 服务器上
- 需要直接调用 Playwright 的 Python API

## 解决方案

### 方法 1: Playwright + DISPLAY=:1 (推荐)

⚠️ **【关键】环境变量必须在 import Playwright 之前设置！**

```python
import os

# ⚠️ 关键：在 import 之前设置环境变量！
os.environ['DISPLAY'] = ':1'
os.environ['XAUTHORITY'] = '/root/.Xauthority'

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,  # 有头模式！
        args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
    )
    page = browser.new_page()
    page.goto("https://www.google.com")
    page.wait_for_timeout(5000)  # 等待页面加载
    browser.close()
```

### 方法 1b: 后台持久运行（推荐用于 VNC 场景）

如果需要浏览器持续显示在 VNC 桌面上：

```python
import os
import time
import signal

# ⚠️ 环境变量必须在 import 之前设置！
os.environ['DISPLAY'] = ':1'
os.environ['XAUTHORITY'] = '/root/.Xauthority'

from playwright.sync_api import sync_playwright

def cleanup():
    try:
        browser.close()
    except:
        pass

signal.signal(signal.SIGINT, lambda s,f: cleanup())
signal.signal(signal.SIGTERM, lambda s,f: cleanup())

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
    )
    page = browser.new_page()
    page.goto("https://www.google.com", timeout=30000)
    print("✅ 浏览器已在 VNC 桌面上运行！")
    print("用户可在 http://localhost:6080 查看")
    time.sleep(3600)  # 保持运行 1 小时
```

### 方法 2: 系统浏览器 + xauth 修复

```bash
# 1. 设置正确的环境变量
export DISPLAY=:1
export XAUTHORITY=/root/.Xauthority

# 2. 验证 X 连接
$DISPLAY xdpyinfo

# 3. 启动浏览器
chromium-browser --new-window https://www.google.com &
```

### 方法 3: 持久化浏览器会话

如果浏览器启动后立即退出：

```bash
export DISPLAY=:1
export XAUTHORITY=/root/.Xauthority

# 后台启动，不等待
nohup chromium-browser --new-window https://www.google.com > /tmp/browser.log 2>&1 &

# 验证进程
ps aux | grep chromium
```

## 环境信息

### VNC 配置

| 项目 | 值 |
|------|-----|
| **VNC 端口** | 5900 |
| **Web 访问** | http://localhost:6080 |
| **显示编号** | :1 |
| **X Authority** | /root/.Xauthority |
| **窗口管理器** | Openbox |
| **桌面环境** | KDE Plasma (plasmashell) |

### 可用浏览器

| 浏览器 | 路径 | 可用性 |
|--------|------|--------|
| Chromium | /usr/bin/chromium-browser | ✅ 推荐 |
| Chrome | /usr/bin/google-chrome | ✅ |
| Firefox | /usr/local/bin/firefox | ❌ Playwright 包装，不可用 |

## 调试命令

```bash
# 检查 VNC 状态
vncserver -list

# 检查 X 显示
w
# 输出示例:
#  15:40:13   2:01  0.00s  0.00s  -bash
#  15:40:15   0:18  0.07s  0.07s  xterm
#  15:40:27   1:01  0.00s  0.00s  chromium-browser

# 检查 X 服务器
DISPLAY=:1 XAUTHORITY=/root/.Xauthority xdpyinfo

# 检查进程和显示对应关系
ps aux | grep -E 'chromium|firefox|Xvnc'

# 从 X 服务器截图（验证窗口是否存在）
DISPLAY=:1 XAUTHORITY=/root/.Xauthority scrot /tmp/screenshot.png
```

## 常见问题

### Q: 浏览器进程存在但 VNC 桌面上看不到

**A**: 可能是窗口在屏幕外。尝试：
```bash
DISPLAY=:1 wmctrl -l  # 列出所有窗口
DISPLAY=:1 wmctrl -r "Chromium" -e 0,0,0,1280,800  # 移动到可见位置
```

### Q: X Authority 错误

**A**: 总是使用完整的命令前缀：
```bash
DISPLAY=:1 XAUTHORITY=/root/.Xauthority <command>
```

### Q: VNC 桌面完全看不到

**A**: 可能需要重启 VNC 服务：
```bash
# 停止
vncserver -kill :1

# 启动
vncserver :1 -geometry 1920x1080 -depth 24
```

## 关键教训

1. **不要用 xvfb-run** - 它创建独立的虚拟显示，VNC 看不到
2. **始终设置 DISPLAY=:1** - 指向 VNC 桌面
3. **始终设置 XAUTHORITY=/root/.Xauthority** - 授权访问
4. **使用 Playwright Python API** - 比包装脚本更可靠
5. **验证用 ps 和截图** - `w` 命令显示的进程不一定在正确的 DISPLAY 上
