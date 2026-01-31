# 前端死代码清理总结

执行时间: 2026-01-31

## 已删除文件 (21)

### 备份目录
- `src/components/agent/.backup/` - 整个备份目录

### Legacy 组件
- `src/components/agent/ConversationSidebarLegacy.tsx`
- `src/components/agent/MessageBubbleLegacy.tsx`

### 未使用组件
- `src/components/agent/InputArea.tsx`
- `src/components/agent/MessageInput.tsx`
- `src/components/agent/MessageList.tsx`
- `src/components/agent/PlanViewer.tsx`
- `src/components/agent/layout/AgentWorkspace.tsx`
- `src/components/project/index.ts`
- `src/components/project/ShareMemoryModal.tsx`
- `src/components/tenant/index.ts`
- `src/components/workbench/Overview.tsx`

### Context
- `src/contexts/DarkModeProvider.tsx`
- `src/contexts/index.ts`

### Pages
- `src/pages/project/agent/AgentLogs.tsx`
- `src/pages/project/agent/AgentPatterns.tsx`
- `src/pages/project/agent/index.ts`
- `src/pages/ProjectDashboard.tsx`

### Test Files
- `src/test/fixtures/componentProps.ts`
- `src/test/fixtures/mockApiResponses.ts`
- `src/test/fixtures/storeState.ts`
- `src/test/debug-i18n.ts`

### Stores
- `src/stores/agent/conversationState.ts`
- `src/stores/agent/index.ts`

### Types
- `src/types/index.ts`

### Services
- `src/services/websocketService.ts`

### Utilities
- `src/utils/retry.ts` (knip 误报，实际不存在)

## 已移除依赖 (10)

### 生产依赖
- `react-window` - 未使用的虚拟滚动库
- `@types/react-window` - 类型定义

### 开发依赖
- `@tailwindcss/postcss` - 未使用的 PostCSS 插件
- `@testing-library/user-event` - 未使用的测试工具
- `autoprefixer` - 未使用的 CSS 前缀处理器
- `nyc` - 未使用的代码覆盖率工具 (已有 vitest coverage)
- `postcss` - 未使用的 CSS 处理器
- `tailwindcss` - 未使用的 CSS 框架

### 分析工具 (清理后移除)
- `depcheck` - 依赖分析工具
- `knip` - 死代码分析工具
- `ts-prune` - TypeScript 导出分析工具

## 已移除配置文件
- `web/.kniprc.ts` - knip 配置

## 测试结果

清理前后测试结果一致:
- Test Files: 93 passed, 25 failed (pre-existing)
- Tests: 1474 passed, 183 failed (pre-existing)
- 清理没有引入新的失败

## 空间节省

- 文件: ~21 个文件
- node_modules 包: ~153 个子包 (通过 pnpm remove)

## 注意事项

1. knip 报告的 332 个 "未使用导出" 主要是类型定义和默认导出，这些是有效的 barrel exports 模式
2. 214 个 "未使用导出的类型" 是用于 API 响应的类型定义，由其他服务使用
3. 构建中存在的 TypeScript 错误是预先存在的，与清理无关
