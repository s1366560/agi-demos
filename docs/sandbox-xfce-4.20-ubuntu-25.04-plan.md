# Ubuntu 25.04 + XFCE 4.20 + VNC 远程桌面完整配置计划

## 需求重述

为 MemStack Sandbox MCP Server 配置完整的远程桌面环境，基于：
- **Ubuntu 25.04 "Plucky Puffin"** (2025年4月17日已发布)
- **XFCE 4.20** (2024年12月15日发布，支持实验性 Wayland)
- **VNC 服务器**：TigerVNC (高性能) + x11vnc (回退)
- **noVNC** (Web 客户端，浏览器访问)

## 当前状态分析

**已完成**:
- Dockerfile 基于 `ubuntu:25.04`
- XFCE 4.20 完整桌面环境已安装
- TigerVNC 和 x11vnc 双服务器配置
- noVNC 1.6.0 Web 客户端
- 完整的 entrypoint.sh 启动脚本

**需要优化的地方**:
1. XFCE 4.20 新特性适配 (实验性 Wayland 支持)
2. TigerVNC 配置目录迁移 (`~/.vnc` → `~/.config/tigervnc`)
3. noVNC 默认配置优化
4. 桌面主题和图标完善

## 实施阶段

### Phase 1: Ubuntu 25.04 仓库优化

**目标**: 确保从最佳镜像源获取 XFCE 4.20

**步骤**:
1. 验证当前阿里云/中科大镜像配置
2. 确认 XFCE 4.20 在 Ubuntu 25.04 仓库版本
3. 如需要，添加 XFCE PPA (针对 25.04 可能不需要)

**预期结果**: `xfce4-about --version` 显示 4.20.x

### Phase 2: TigerVNC 配置适配

**背景**: Ubuntu 25.04 中 TigerVNC 配置位置变更

**步骤**:
1. 更新 `~/.config/tigervnc/xstartup` (新位置)
2. 确保 XFCE 4.20 会话启动参数正确
3. 处理 `DISPLAY` 环境变量 (已配置为 :99)
4. 验证无密码认证配置 (`-securitytypes none`)

**关键配置**:
```bash
# 新配置目录
/home/sandbox/.config/tigervnc/xstartup
# 老目录已废弃
/home/sandbox/.vnc/  # 需清理避免迁移错误
```

### Phase 3: XFCE 4.20 桌面组件优化

**新特性利用**:

| 组件 | Ubuntu 25.04 状态 | 配置文件 |
|------|------------------|----------|
| xfce4-session | 4.20.x | `xfce4-session.xml` |
| xfce4-panel | 4.20.x | `xfce4-panel.xml` |
| xfce4-desktop | 4.20.x | `xfce4-desktop.xml` |
| xfwm4 | 4.20.x | `xfwm4.xml` |
| whiskermenu | 4.20.x | `whiskermenu-1.rc` |
| xsettings | 4.20.x | `xsettings.xml` |

**步骤**:
1. 更新所有 XFCE 配置文件以兼容 4.20
2. 添加 SVG 背景支持 (4.20 新特性)
3. 配置实验性 Wayland 支持 (可选，X11 仍然是默认)
4. 优化面板插件布局

### Phase 4: noVNC Web 客户端配置

**目标**: 优化浏览器访问体验

**步骤**:
1. 配置 `novnc-defaults.json` 默认设置
2. 设置自动连接参数
3. 配置合适的缩放和显示质量
4. 添加键盘快捷键支持

**关键配置**:
```json
{
  "host": "localhost",
  "port": 5901,
  "encrypt": false,
  "true_color": true,
  "local_cursor": true,
  "shared": true,
  "view_only": false,
  "connect_timeout": 5,
  "resize": "scale"
}
```

### Phase 5: 字体和主题完善

**步骤**:
1. 验证 CJK 字体 (fonts-noto-cjk)
2. 配置 Greybird/Arc 主题
3. 设置图标主题 (xfce4-icon-theme)
4. 添加表情符号支持 (fonts-noto-color-emoji)

### Phase 6: 测试验证

**测试清单**:
- [ ] TigerVNC 启动成功 (端口 5901)
- [ ] noVNC Web 界面可访问 (端口 6080)
- [ ] XFCE 4.20 会话正常加载
- [ ] 面板和菜单正常显示
- [ ] 中文/日文/韩文字符正确渲染
- [ ] ttyd Web 终端工作正常 (端口 7681)

## 依赖关系

```
Phase 1 (仓库) → Phase 2 (TigerVNC) → Phase 3 (XFCE 4.20) → Phase 4 (noVNC) → Phase 5 (主题) → Phase 6 (测试)
```

## 风险评估

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| Ubuntu 25.04 太新，社区文档少 | MEDIUM | 参考 24.04/24.10 指南，基本命令兼容 |
| TigerVNC 配置目录迁移 | LOW | 已在 entrypoint.sh 中处理 |
| XFCE 4.20 Wayland 实验性 | LOW | 默认使用 X11，Wayland 可选 |
| noVNC 兼容性 | LOW | 1.6.0 是稳定版本 |

## 参考资料

- [XFCE 4.20 Changelog](https://www.xfce.org/download/changelogs/4.20)
- [XFCE 4.20 Release Announcement](https://www.xfce.org/about/news/?post=1734220800)
- [Ubuntu 25.04 Release Notes](https://discourse.ubuntu.com/t/plucky-puffin-release-notes/48687)
- [TigerVNC Ubuntu 配置指南](https://www.cyberciti.biz/faq/install-and-configure-tigervnc-server-on-ubuntu-18-04/)
- [noVNC GitHub](https://github.com/novnc/noVNC)
- [如何在 Ubuntu 上安装 XFCE 4.20 (Ubuntu Handbook)](https://ubuntuhandbook.org/index.php/2024/12/install-xfce-4-20-ubuntu/)
- [在 Ubuntu 24.04 上配置 VNC 远程桌面](https://linuxstory.org/ubuntu-24-04-vnc/)
- [TigerVNC + XFCE4 设置指南](https://canwdev.github.io/Linux/Debian_Ubuntu/Ubuntu%2520Server%2520%25E5%25AE%2589%25E8%25A3%2585%2520TigerVNC%2520%252B%2520Xfce4%2520%25E6%25A1%258C%25E9%259D%25A2%25E7%258E%25AF%25E5%25A2%2583/)
- [XFCE 4.20 发布说明 (OMG! Ubuntu!)](https://www.omgubuntu.co.uk/2024/12/xfce-4-20-released-this-is-whats-new)

## 实施进度

- [x] Phase 1: Ubuntu 25.04 仓库优化
- [x] Phase 2: TigerVNC 配置适配
- [x] Phase 3: XFCE 4.20 桌面组件优化
- [x] Phase 4: noVNC Web 客户端配置
- [x] Phase 5: 字体和主题完善
- [x] Phase 6: 测试验证

## 实施变更摘要

### 已修改文件

1. **Dockerfile**
   - 添加更多 XFCE 4.20 面板插件 (diskperf, netload, cpugraph, weather, genmon)
   - 添加更多字体支持 (fonts-liberation, fonts-dejavu-core)
   - 更新 noVNC 测试脚本包含

2. **docker/vnc-configs/xstartup**
   - 重写为使用 `xfce4-session` 启动完整桌面环境
   - 自动复制默认 XFCE 配置
   - 正确处理 D-Bus 会话

3. **scripts/entrypoint.sh**
   - 简化 xstartup 创建逻辑，直接复制模板

4. **docker/xfce-configs/xsettings.xml**
   - 更新为使用 Greybird 主题
   - 使用 Noto Sans 字体 (更好的 CJK 支持)

5. **docker/xfce-configs/xfwm4.xml**
   - 更新为使用 Greybird 主题
   - 添加更多窗口管理器优化设置

6. **docker/xfce-configs/xfce4-desktop.xml**
   - 更新为使用 Virtual1 显示器名称
   - 添加桌面字体配置

7. **docker/vnc-configs/novnc-defaults.json**
   - 添加更多显示和交互选项
   - 配置压缩和质量设置

8. **docker/vnc-configs/test-complete-setup.sh** (新增)
   - 完整的 XFCE 4.20 + VNC 设置验证脚本
   - 测试 12 个关键组件

9. **Makefile**
   - 添加 `sandbox-test-complete` 命令

### 测试命令

```bash
# 构建镜像
make sandbox-build

# 启动容器 (TigerVNC)
make sandbox-run

# 运行完整测试验证
make sandbox-test-complete

# 查看 Web 界面
# http://localhost:6080/vnc.html
```
