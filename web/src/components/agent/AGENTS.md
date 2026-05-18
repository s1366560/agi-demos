# web/src/components/agent/

Agent and timeline UI. Current immediate entries: 86. The `chat/` subdirectory has 40
TypeScript/TSX files.

Last checked against code: 2026-05-18.

## Top-Level Components

| Component | Purpose |
|---|---|
| `AgentChatContent.tsx` | Main agent workspace controller and layout composition. |
| `AgentChatInputArea.tsx` / `InputBar.tsx` | Prompt input, file upload, commands, mention UX. |
| `MessageArea.tsx` | Conversation/timeline list container. |
| `MessageBubble.tsx` | Message bubble rendering. |
| `ConversationSidebar.tsx` and `layout/ChatHistorySidebar.tsx` | Conversation history/navigation. |
| `TaskList.tsx` | Agent todo/task projection UI. |
| `RightPanel.tsx`, `rightPanel/` | Context, execution, artifact, sandbox side panels. |
| `UnifiedHITLPanel.tsx`, HITL cards | Human-in-the-loop request UI. |
| `ProjectAgentStatusBar.tsx` | Agent lifecycle/status controls. |
| `timeline/`, `timeline-items/` | Timeline and event-specific renderers. |
| `sandbox/` | Desktop/terminal/sandbox status UI. |
| `canvas/` | Artifact/canvas panel rendering. |

## Data Flow

```text
AgentWorkspace page
  -> AgentChatContent
  -> useAgentV3Store / stores/agent/*
  -> agentService.ts WebSocket + REST
  -> backend /api/v1/agent/ws and /api/v1/agent/*
```

`AgentWorkspace` lives at `web/src/pages/tenant/AgentWorkspace.tsx` and passes tenant,
project, workspace, and conversation context into the agent UI.

## Chat Subdirectory

`chat/` contains message rendering, markdown/code/mermaid/KaTeX support, search, model
controls, suggestions, voice UI, variable input, and streaming message components.

## Rules

- Keep timeline event support aligned with `web/src/utils/sseEventAdapter.ts` and
  `web/src/services/agent/messageRouter.ts`.
- Use stable dimensions for timeline/tool/HITL cards to avoid layout jumps.
- Use `useShallow` when selecting multiple values from Zustand.
- Do not reintroduce old `components/agentV3/` assumptions; the active UI is under
  `components/agent/`.
