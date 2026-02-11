# Merge Duplicate Conversation Sidebars

## Problem
The `/tenant` page renders **two** conversation list sidebars simultaneously:
1. **TenantChatSidebar** — rendered by `TenantLayout.tsx` as the layout-level left sidebar
2. **ConversationSidebar** — rendered by `AgentChatContent.tsx` inside the page content area

Both show the same conversation list from the same store, creating visual duplication.

## Architecture (Current)

```
TenantLayout
├── TenantChatSidebar (LEFT SIDEBAR #1) ← project selector + conversations
├── <main>
│   ├── AppHeader
│   └── <Outlet> → AgentWorkspace
│       └── AgentChatContent
│           ├── ConversationSidebar (LEFT SIDEBAR #2) ← labels + HITL + conversations
│           ├── Chat area
│           └── Right panel
```

## Analysis

| Feature | TenantChatSidebar | ConversationSidebar |
|---------|-------------------|---------------------|
| Project selector | Yes | No |
| Conversations list | Yes | Yes |
| Labels/colors | No | Yes |
| HITL status indicators | No | Yes |
| Draggable resize | Yes (complex) | No (fixed width) |
| Pagination/infinite scroll | Yes | No |
| New chat | Yes | Yes |
| Rename/Delete | Yes | Yes |
| Mobile drawer | No | Yes (MobileSidebarDrawer) |
| Lines of code | ~663 | ~644 |

## Approach: Remove ConversationSidebar from AgentChatContent

**Rationale:**
- `TenantChatSidebar` is the **layout-level** sidebar, rendered once for ALL /tenant routes
- `ConversationSidebar` only appears inside AgentChatContent, creating duplication
- Keeping the layout-level sidebar is architecturally correct
- Labels + HITL can be added to TenantChatSidebar later if needed

## Workplan

### AgentChatContent.tsx
- [ ] 1. Remove ConversationSidebar import
- [ ] 2. Remove `sidebarContent` useMemo
- [ ] 3. Remove MobileSidebarDrawer rendering
- [ ] 4. Remove desktop `<aside>` sidebar wrapper
- [ ] 5. Remove `sidebarCollapsed` state and related code
- [ ] 6. Clean up unused imports
- [ ] 7. Remove mobile sidebar toggle button from chat header

### TenantLayout.tsx
- [ ] 8. Add MobileSidebarDrawer for mobile (if not present)

### Verify
- [ ] 9. TypeScript build passes
- [ ] 10. No unused imports/variables
