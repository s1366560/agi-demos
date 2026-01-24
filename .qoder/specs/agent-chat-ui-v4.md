# Agent V3 UI 增量升级计划 - 可视化组件集成

## 概述

在现有 AgentV3 UI 基础上增量升级，将新创建的可视化组件（ActivityTimeline、TokenUsageChart、ToolCallVisualization）集成到消息气泡中，提供多视角的执行细节展示。

---

## 核心变更

### 新建文件

| 文件路径 | 描述 |
|----------|------|
| `web/src/components/agentV3/ExecutionDetailsPanel.tsx` | 执行细节面板，统一管理多视图切换 |
| `web/src/utils/agentDataAdapters.ts` | 数据转换适配器，Store 数据到组件 Props |

### 修改文件

| 文件路径 | 修改内容 |
|----------|----------|
| `web/src/components/agentV3/MessageBubble.tsx` | 替换 ThinkingChain 为 ExecutionDetailsPanel |
| `web/src/components/agentV3/index.ts` | 导出新组件 |

---

## 架构设计

### UI 结构
```
MessageBubble (消息容器)
├── Markdown 内容
└── ExecutionDetailsPanel (可折叠)
    ├── [Tab 1] 思考过程 (ThinkingChain - 默认)
    ├── [Tab 2] 活动时间线 (ActivityTimeline)  
    ├── [Tab 3] 工具调用 (ToolCallVisualization)
    └── [Tab 4] Token 使用 (TokenUsageChart - 有数据时显示)
```

### 数据流
```
Message.metadata
├── timeline: TimelineItem[]         → ActivityTimeline
├── tool_executions: Record<...>     → ToolCallVisualization (转换)
├── thoughts: string[]               → ThinkingChain
└── token_usage?: {...}              → TokenUsageChart (graceful degradation)
```

---

## 实现步骤

### 步骤 1: 创建数据适配器

**文件**: `web/src/utils/agentDataAdapters.ts`

```typescript
import type { Message, ToolCall, ToolResult } from '../types/agent';
import type { TimelineItem, ToolExecutionInfo } from '../components/agent/execution/ActivityTimeline';
import type { ToolExecutionItem } from '../components/agent/execution/ToolCallVisualization';
import type { TokenData, CostData } from '../components/agent/execution/TokenUsageChart';

// Timeline 数据适配
export function adaptTimelineData(message: Message) {
  return {
    timeline: (message.metadata?.timeline as TimelineItem[]) || [],
    toolExecutions: (message.metadata?.tool_executions as Record<string, ToolExecutionInfo>) || {},
    toolCalls: message.tool_calls || [],
    toolResults: message.tool_results || []
  };
}

// Tool 可视化数据适配
export function adaptToolVisualizationData(message: Message): ToolExecutionItem[] {
  const timeline = (message.metadata?.timeline as TimelineItem[]) || [];
  const executions = (message.metadata?.tool_executions as Record<string, ToolExecutionInfo>) || {};
  const results = message.tool_results || [];

  return timeline
    .filter(item => item.type === 'tool_call')
    .map((item, index) => {
      const toolName = item.toolName || 'unknown';
      const execution = executions[toolName];
      const result = results.find(r => r.tool_name === toolName);
      
      return {
        id: item.id,
        toolName,
        input: item.toolInput || {},
        output: result?.result,
        status: result ? (result.error ? 'failed' : 'success') : 'running',
        startTime: execution?.startTime || item.timestamp,
        endTime: execution?.endTime,
        duration: execution?.duration,
        stepNumber: index + 1,
        error: result?.error
      };
    });
}

// Token 数据提取 (graceful degradation)
export function extractTokenData(message: Message): { tokenData?: TokenData; costData?: CostData } {
  const metadata = message.metadata as any;
  const tokenUsage = metadata?.token_usage || metadata?.usage || metadata?.llm_usage;
  
  if (!tokenUsage) return {};
  
  return {
    tokenData: {
      input: tokenUsage.input_tokens || tokenUsage.prompt_tokens || 0,
      output: tokenUsage.output_tokens || tokenUsage.completion_tokens || 0,
      reasoning: tokenUsage.reasoning_tokens,
      total: tokenUsage.total_tokens || 0
    },
    costData: metadata?.cost ? {
      total: metadata.cost.total || 0,
      breakdown: metadata.cost.breakdown
    } : undefined
  };
}
```

### 步骤 2: 创建 ExecutionDetailsPanel

**文件**: `web/src/components/agentV3/ExecutionDetailsPanel.tsx`

```typescript
import React, { useState, useMemo } from 'react';
import { Collapse, Segmented, Tag } from 'antd';
import {
  BulbOutlined,
  ClockCircleOutlined,
  ApiOutlined,
  DollarOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import { ThinkingChain } from './ThinkingChain';
import { ActivityTimeline } from '../agent/execution/ActivityTimeline';
import { ToolCallVisualization } from '../agent/execution/ToolCallVisualization';
import { TokenUsageChart } from '../agent/execution/TokenUsageChart';
import { 
  adaptTimelineData, 
  adaptToolVisualizationData, 
  extractTokenData 
} from '../../utils/agentDataAdapters';
import type { Message } from '../../types/agent';

type ViewType = 'thinking' | 'activity' | 'tools' | 'tokens';

export interface ExecutionDetailsPanelProps {
  message: Message;
  isStreaming?: boolean;
  compact?: boolean;
  defaultView?: ViewType;
}

export const ExecutionDetailsPanel: React.FC<ExecutionDetailsPanelProps> = ({
  message,
  isStreaming = false,
  compact = false,
  defaultView = 'thinking',
}) => {
  const [activeView, setActiveView] = useState<ViewType>(defaultView);

  // Memoized data transformations
  const thinkingData = useMemo(() => adaptTimelineData(message), [message]);
  const activityData = useMemo(() => 
    activeView === 'activity' ? adaptTimelineData(message) : null, 
    [message, activeView]
  );
  const toolsData = useMemo(() => 
    activeView === 'tools' ? adaptToolVisualizationData(message) : null, 
    [message, activeView]
  );
  const { tokenData, costData } = useMemo(() => extractTokenData(message), [message]);

  // Check if we have any execution data
  const hasTimeline = thinkingData.timeline.length > 0;
  const hasThoughts = ((message.metadata?.thoughts as string[]) || []).length > 0;
  const hasTools = (toolsData?.length || 0) > 0 || (message.tool_calls?.length || 0) > 0;
  const hasTokenData = !!tokenData;

  if (!hasTimeline && !hasThoughts && !hasTools && !isStreaming) {
    return null;
  }

  // Build view options dynamically
  const viewOptions = [
    { value: 'thinking', label: '思考', icon: <BulbOutlined /> },
    { value: 'activity', label: '时间线', icon: <ClockCircleOutlined /> },
    ...(hasTools ? [{ value: 'tools', label: '工具', icon: <ApiOutlined /> }] : []),
    ...(hasTokenData ? [{ value: 'tokens', label: 'Token', icon: <DollarOutlined /> }] : []),
  ];

  const header = (
    <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
      <InfoCircleOutlined />
      <span className="text-xs font-medium">
        {isStreaming ? '执行中...' : '执行细节'}
      </span>
      {hasTokenData && tokenData && (
        <Tag color="blue" className="ml-auto text-[10px]">
          {tokenData.total.toLocaleString()} tokens
        </Tag>
      )}
    </div>
  );

  return (
    <Collapse
      ghost
      size="small"
      defaultActiveKey={isStreaming ? ['1'] : []}
      className="mb-4 bg-slate-50/50 dark:bg-slate-800/30 rounded-lg border border-slate-100 dark:border-slate-700"
      items={[{
        key: '1',
        label: header,
        children: (
          <div className="space-y-3">
            <Segmented
              size="small"
              value={activeView}
              onChange={(value) => setActiveView(value as ViewType)}
              options={viewOptions.map(opt => ({
                value: opt.value,
                label: (
                  <span className="flex items-center gap-1 px-1">
                    {opt.icon}
                    <span className="text-xs">{opt.label}</span>
                  </span>
                ),
              }))}
            />

            {activeView === 'thinking' && (
              <ThinkingChain
                thoughts={(message.metadata?.thoughts as string[]) || []}
                toolCalls={message.tool_calls}
                toolResults={message.tool_results}
                isThinking={isStreaming}
                toolExecutions={thinkingData.toolExecutions}
                timeline={thinkingData.timeline}
              />
            )}

            {activeView === 'activity' && activityData && (
              <ActivityTimeline
                timeline={activityData.timeline}
                toolCalls={activityData.toolCalls}
                toolResults={activityData.toolResults}
                toolExecutions={activityData.toolExecutions}
                isActive={isStreaming}
                compact={compact}
              />
            )}

            {activeView === 'tools' && toolsData && (
              <ToolCallVisualization
                toolExecutions={toolsData}
                mode="grid"
                compact={compact}
                allowModeSwitch={true}
              />
            )}

            {activeView === 'tokens' && tokenData && (
              <TokenUsageChart
                tokenData={tokenData}
                costData={costData}
                variant={compact ? 'compact' : 'detailed'}
              />
            )}
          </div>
        ),
      }]}
    />
  );
};

export default ExecutionDetailsPanel;
```

### 步骤 3: 修改 MessageBubble

**文件**: `web/src/components/agentV3/MessageBubble.tsx`

找到 ThinkingChain 的使用位置，替换为 ExecutionDetailsPanel：

```typescript
// 添加导入
import { ExecutionDetailsPanel } from './ExecutionDetailsPanel';

// 替换 ThinkingChain 调用
// 原代码:
// <ThinkingChain thoughts={thoughts} ... />

// 新代码:
{!isUser && (
  <ExecutionDetailsPanel
    message={message}
    isStreaming={isStreaming && message.content.length === 0}
    compact={false}
    defaultView="thinking"
  />
)}
```

### 步骤 4: 更新组件导出

**文件**: `web/src/components/agentV3/index.ts`

添加新组件导出：
```typescript
export { ExecutionDetailsPanel } from './ExecutionDetailsPanel';
export type { ExecutionDetailsPanelProps } from './ExecutionDetailsPanel';
```

---

## 向后兼容策略

1. **默认视图**：首次加载显示 ThinkingChain（保持用户习惯）
2. **数据结构不变**：仅读取现有 metadata，不修改写入逻辑
3. **Token 降级**：无 token_usage 数据时隐藏 Token 标签
4. **快速回滚**：仅需回退 MessageBubble.tsx 一行代码

---

## 验证步骤

### 1. 类型检查
```bash
cd web && pnpm run type-check
```

### 2. 构建验证
```bash
cd web && pnpm run build
```

### 3. 手动测试流程
1. 启动开发服务器：`make dev-web`
2. 访问 `/project/:projectId/agent`
3. 发送消息触发 Agent 执行
4. 验证执行细节面板显示
5. 测试视图切换（思考 → 时间线 → 工具 → Token）
6. 验证降级场景（无 Token 数据时隐藏 Token 标签）

---

## 文件清单

| 操作 | 文件路径 |
|------|----------|
| 新建 | `web/src/utils/agentDataAdapters.ts` |
| 新建 | `web/src/components/agentV3/ExecutionDetailsPanel.tsx` |
| 修改 | `web/src/components/agentV3/MessageBubble.tsx` |
| 修改 | `web/src/components/agentV3/index.ts` |
