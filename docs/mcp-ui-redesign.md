# MCP UI 重新设计文档

## 概述

本次重新设计旨在为 MCP (Model Context Protocol) 管理界面带来现代化、优雅的 UI/UX 体验，提升视觉层次感和交互流畅度。

## 设计目标

### 1. 现代化视觉风格
- **圆润设计语言**: 使用 `rounded-xl` 和 `rounded-2xl` 替代旧式的 `rounded-lg`
- **渐变装饰**: 为卡片添加顶部渐变边框，增强视觉吸引力
- **柔和阴影**: 使用多层阴影创造深度感
- **流畅动画**: 添加过渡效果和微动画提升交互体验

### 2. 改进的信息层次
- **清晰的视觉层次**: 通过字体大小、颜色、间距建立明确的信息层级
- **状态可视化**: 使用颜色编码和图标直观展示服务器/应用状态
- **数据密度优化**: 在有限空间内展示更多信息，同时保持可读性

### 3. 增强的交互体验
- **悬停反馈**: 卡片悬停时显示阴影和边框变化
- **加载状态**: 使用动画指示器清晰展示加载状态
- **错误提示**: 醒目的错误横幅和行内错误消息
- **平滑过渡**: 所有状态变化都有流畅的过渡动画

## 组件架构

### 核心组件

```
web/src/components/mcp/
├── types.ts                 # 类型定义和辅助函数
├── styles.ts                # 样式常量和主题配置
├── index.v2.ts              # V2 组件导出
├── McpServerListV2.tsx      # 主页面组件
├── McpServerTabV2.tsx       # 服务器标签页
├── McpToolsTabV2.tsx        # 工具标签页
├── McpAppsTabV2.tsx         # 应用标签页
├── McpServerCardV2.tsx      # 服务器卡片
├── McpAppCardV2.tsx         # 应用卡片
└── McpToolItemV2.tsx        # 工具列表项
```

### 样式系统

#### 运行时状态样式
```typescript
RUNTIME_STATUS_STYLES = {
  running: { dot: 'bg-emerald-500', label: '运行中', ... },
  starting: { dot: 'bg-blue-500', label: '启动中', ... },
  error: { dot: 'bg-red-500', label: '错误', ... },
  disabled: { dot: 'bg-slate-400', label: '已禁用', ... },
  unknown: { dot: 'bg-amber-500', label: '未知', ... },
}
```

#### 服务器类型样式
```typescript
SERVER_TYPE_STYLES = {
  stdio: { bg: 'bg-blue-50', icon: 'terminal', gradient: 'from-blue-500 to-cyan-500' },
  sse: { bg: 'bg-emerald-50', icon: 'stream', gradient: 'from-emerald-500 to-teal-500' },
  http: { bg: 'bg-violet-50', icon: 'http', gradient: 'from-violet-500 to-purple-500' },
  websocket: { bg: 'bg-orange-50', icon: 'hub', gradient: 'from-orange-500 to-amber-500' },
}
```

## 主要改进

### 1. 服务器卡片 (McpServerCardV2)

**新特性:**
- 顶部渐变边框标识服务器类型
- 脉冲动画的运行状态指示器
- 改进的标签系统，展示更多上下文信息
- 折叠式的工具列表预览
- 醒目的错误提示横幅
- 底部状态栏显示最后同步时间和测试状态

**视觉改进:**
```tsx
// 旧版
<div className="rounded-lg border">

// 新版
<div className="rounded-2xl border hover:shadow-xl">
  <div className="absolute top-0 h-1 bg-gradient-to-r from-blue-500 to-cyan-500" />
```

### 2. 应用卡片 (McpAppCardV2)

**新特性:**
- 来源指示器（AI 创建 vs 用户添加）
- 资源地址展示区域
- 文件大小显示
- 改进的状态标签
- 重试按钮的友好交互

**视觉改进:**
- 渐变图标背景
- 更清晰的信息层次
- 柔和的颜色方案

### 3. 工具列表 (McpToolItemV2)

**新特性:**
- 可展开的详细信息
- 服务器类型标识
- 输入模式展示
- 平滑的展开/折叠动画

**视觉改进:**
- 更大的点击区域
- 更清晰的视觉反馈
- 改进的代码块展示样式

### 4. 统计卡片 (StatsCard)

**新特性:**
- 装饰性渐变背景元素
- 图标悬停缩放效果
- 改进的数据展示

### 5. 筛选工具栏

**新特性:**
- 统一的圆角设计
- 改进的筛选器布局
- 实时筛选计数
- 一键清除筛选

## 响应式设计

### 断点配置
```css
sm: 640px   - 小屏手机
md: 768px   - 平板
lg: 1024px  - 小屏笔记本
xl: 1280px  - 桌面
2xl: 1536px - 大屏桌面
```

### 自适应布局
- **移动端**: 单列布局，垂直堆叠
- **平板**: 双列网格，水平筛选器
- **桌面**: 三列网格，完整工具栏

## 深色模式支持

所有组件都完全支持深色模式：

```tsx
// 示例：卡片背景
bg-white dark:bg-slate-800

// 示例：文本颜色
text-slate-900 dark:text-white

// 示例：边框
border-slate-200 dark:border-slate-700/60
```

## 动画系统

### 内置动画类
```typescript
ANIMATION_CLASSES = {
  pulse: 'animate-pulse',           // 脉冲效果
  spin: 'animate-spin',             // 旋转加载
  bounce: 'animate-bounce',         // 弹跳效果
  fadeIn: 'animate-in fade-in duration-300',
  slideUp: 'animate-in slide-in-from-bottom-4 duration-300',
  scaleIn: 'animate-in zoom-in-95 duration-200',
}
```

### 过渡效果
- 所有交互元素都有 `transition-all duration-200/300`
- 悬停状态使用 `hover:shadow-xl` 增强反馈
- 卡片展开使用 `animate-in slide-in-from-top-2`

## 使用示例

### 在路由中使用新组件

```tsx
// 替换旧版 MCP 页面
import { McpServerListV2 } from '@/components/mcp/McpServerListV2';

function App() {
  return (
    <Routes>
      <Route path="/mcp" element={<McpServerListV2 />} />
    </Routes>
  );
}
```

### 使用独立标签页组件

```tsx
import { McpServerTabV2, McpToolsTabV2, McpAppsTabV2 } from '@/components/mcp';

function CustomMcpDashboard() {
  return (
    <div>
      <McpServerTabV2 />
      <McpToolsTabV2 />
      <McpAppsTabV2 />
    </div>
  );
}
```

## 性能优化

1. **React.memo**: 卡片组件使用 `React.memo` 避免不必要的重渲染
2. **useMemo**: 计算密集型操作使用 `useMemo` 缓存
3. **useCallback**: 事件处理函数使用 `useCallback` 优化
4. **懒加载**: 大型列表考虑虚拟滚动（未来优化）

## 可访问性

- 所有按钮都有 `aria-label`
- 支持键盘导航
- 颜色对比度符合 WCAG 标准
- 图标都有文本标签或 `title` 属性

## 未来改进计划

1. **虚拟滚动**: 优化大量工具/应用的渲染性能
2. **拖拽排序**: 支持自定义服务器排序
3. **批量操作**: 支持批量启用/禁用/删除
4. **实时监控**: WebSocket 连接实时显示服务器状态
5. **图表可视化**: 添加服务器运行状况图表
6. **搜索增强**: 支持高级搜索和保存的筛选条件

## 迁移指南

### 从 V1 迁移到 V2

1. **更新导入路径**
```tsx
// 旧版
import { McpServerList } from '@/components/mcp/McpServerList';

// 新版
import { McpServerListV2 } from '@/components/mcp/McpServerListV2';
```

2. **API 兼容性**
- V2 组件保持与 V1 相同的 Store 接口
- 无需修改现有的状态管理逻辑
- 筛选器状态结构略有变化，需要更新

3. **样式自定义**
- 通过 `styles.ts` 中的常量自定义主题
- 支持 Tailwind 配置扩展

## 设计原则

1. **一致性**: 统一的圆角、间距、颜色系统
2. **清晰度**: 信息层次分明，易于理解
3. **反馈**: 所有操作都有明确的视觉反馈
4. **优雅**: 精致的细节和流畅的动画
5. **包容**: 完善的深色模式和可访问性支持

## 技术栈

- **React 19**: 最新版本，利用所有性能优化
- **TypeScript**: 完整的类型安全
- **Tailwind CSS 4**: 最新的原子化 CSS 框架
- **Ant Design 6**: UI 组件库
- **Lucide Icons**: 现代化图标库
- **Zustand**: 轻量级状态管理

---

**版本**: 2.0.0  
**更新日期**: 2026 年 2 月 20 日  
**作者**: MCP UI Design Team
