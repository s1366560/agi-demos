# web/src/components/agent/

Agent chat UI -- the largest component directory (57 entries: files + subdirs).

## Top-Level Components

| Component | Purpose |
|-----------|---------|
| `AgentChatContent.tsx` | Main layout controller (~950 lines). 4 modes: chat/task/code/canvas. Cmd+1/2/3/4 switching |
| `AgentChatInputArea.tsx` | Input area with file upload, slash commands, mention popover |
| `AgentChatHooks.ts` | Shared hooks for agent chat (conversation init, keyboard shortcuts) |
| `MessageArea.tsx` | Message list container (virtualized) |
| `MessageBubble.tsx` | Individual message rendering (user vs assistant) |
| `InputBar.tsx` | Text input bar with submit handling |
| `EmptyState.tsx` | Empty conversation state (onboarding prompt) |
| `ConversationSidebar.tsx` | Conversation list sidebar |
| `TaskList.tsx` | Agent task list display (todo items from todowrite tool) |
| `RightPanel.tsx` | Right panel container (Plan/Terminal/Desktop tabs) |
| `ProjectSelector.tsx` | Project dropdown for conversation context |
| `CostTracker.tsx` | Token/cost display for current conversation |

## chat/ Subdirectory (34 files)

Core chat message rendering and interaction components:

| Component | Purpose |
|-----------|---------|
| `AssistantMessage.tsx` | Assistant message with thought/action/observe sections |
| `MessageRenderer.tsx` | Dispatches message type to correct renderer |
| `VirtualizedMessageList.tsx` | Performance: windowed rendering for long conversations |
| `MessageStream.tsx` | Live streaming message display |
| `MarkdownContent.tsx` | Markdown rendering with syntax highlighting |
| `CodeBlock.tsx` | Fenced code block with copy button |
| `MermaidBlock.tsx` | Mermaid diagram rendering |
| `ThinkingBlock.tsx` | Collapsible thinking/reasoning display |
| `ThreadView.tsx` | Threaded conversation view |
| `ChatSearch.tsx` | Search within conversation messages |
| `OnboardingTour.tsx` | First-time user tour |
| `TimelineEventRenderer.tsx` | SSE timeline event rendering (tool calls, HITL, etc.) |

## Other Subdirectories

| Dir | Purpose |
|-----|---------|
| `canvas/` | Artifact canvas panel (code preview, file viewer) |
| `comparison/` | Side-by-side conversation comparison |
| `context/` | Context window management UI |
| `execution/` | Execution details panel |
| `layout/` | Layout mode selector (chat/task/code/canvas) |
| `message/` | Message-level components |
| `messageBubble/` | MessageBubble sub-components |
| `patterns/` | Workflow pattern display |
| `rightPanel/` | Right panel tab content |
| `sandbox/` | Sandbox terminal/desktop integration |
| `shared/` | Shared sub-components |
| `timeline/` | Timeline event components |
| `types/` | Component-local TypeScript types |

## Data Flow

- `AgentChatContent` reads from `useAgentV3Store` (conversation state, messages, streaming)
- SSE events arrive via WebSocket -> `agentService` -> `streamEventHandlers.ts` -> Zustand store update -> re-render
- `MessageArea` uses `VirtualizedMessageList` for performance with long conversations
- HITL (Human-in-the-Loop) cards render inline via `InlineHITLCard.tsx` and `UnifiedHITLPanel.tsx`

## Integration Point

- Page: `pages/tenant/AgentWorkspace.tsx` renders `AgentChatContent`
- Store: `stores/agentV3.ts` (main), `stores/agent/` (sub-modules)
- Service: `services/agentService.ts` (WebSocket + REST)

## Gotchas

- `AgentChatContent` is ~950 lines -- read it in sections via offset
- `chat/` alone has 34 files -- most message rendering logic lives here
- `index.ts` barrel exports `MessageArea`, `InputBar`, `ProjectAgentStatusBar` -- used by `AgentChatContent`
- `useShallow` required for all multi-value Zustand selectors (see root AGENTS.md)
