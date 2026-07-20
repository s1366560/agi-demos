# MemStack Desktop — My Work Mission Control

Interactive high-fidelity prototype for the selected desktop-client direction. It demonstrates one shared task kernel across two capability modes:

- **Work:** research, source lineage, executive brief artifacts, human input, review, and steering.
- **Code:** isolated worktree execution, plan/changes/terminal/preview tabs, approval boundaries, verification, and editor handoff.
- **Settings → AI resources:** Models uses a Provider-first flow for authentication, endpoint verification, model discovery, model enablement, and workspace routing. Skills, Plugins, and Agents retain the governed catalog/detail pattern with specialized dependency, permission, validation, and audit views.
- **Identity and workspace context:** Sign in with workspace SSO or email, restore a trusted local prototype session, sign out from the account menu, and switch Tenant → Project from Settings → Workspace.
- **Workspace navigation:** Within the active Project, the sidebar presents a Codex-style thread list grouped by Workspace with inline status indicators; selecting a thread opens the narrative conversation beside a mode-aware Work Canvas for plan, changes/artifact, terminal/sources, and verification. My Work acts as an inbox aggregating Needs input / Running / Ready threads across modes.
- **Independent Settings window:** Account, workspace context, preferences, and AI resources open in a focused modal window without replacing the task workspace underneath.
- **Internationalization:** English and Simplified Chinese can be switched instantly from Settings → General and the preference is persisted locally.

## Core interactions

The shell follows the Codex app thread-centric model: the thread is the primary workspace, and every flow starts from or returns to a thread.

- Browse threads in the sidebar, grouped by Workspace with inline status (Needs input pulse, Running pulse, Ready check); click any row to open the thread directly.
- Create a thread from the composer-first home page: a centered composer with Mode (Work/Code), Model, Reasoning effort, and Permission mode selectors, plus suggested prompts and recent threads.
- Send a prompt and watch the agent insert an inline Plan card in the thread; edit, trim, toggle, or add steps, then Approve plan or Ask agent to revise — no wizard.
- Resolve HITL approvals from the inline approval card pinned above the composer (Allow once / Always allow / Deny with scope details); the decision lands in the timeline as a system event and the run resumes. No modal dialogs.
- Use My Work as an inbox: cross-mode cards grouped by Needs input / Running / Ready to review; clicking a card jumps straight into the owning thread.
- Read the narrative thread, expand grouped tool activity, switch Work Canvas views, pause and resume the active run, and steer from the thread composer.
- Mode is a thread property shown as a badge in the header breadcrumb (Project → Workspace → Thread), alongside branch/workspace and model context plus Share / Archive actions.
- Sign in, open Account settings from the profile menu, choose a Tenant and then one of its Projects, and apply the new workspace context.
- Search from the sidebar; Settings opens as an independent modal window.
- Open Settings → Models to test Provider connection, manual Model ID, routing, and the three-step Add Provider wizard. Switch between the other AI resources or change the interface language under General.
- Search and filter resource catalogs, select records, switch detail tabs, and save model/agent/skill configuration drafts.
- Run skill validation, install/update/disable plugins, pause/enable agents, and create governed resource drafts.

## Local preview

```bash
npm install
npm run dev
```

The production bundle is verified with `npm run build`. The Codex-aligned thread-centric flow is captured in `qa/codex-01-home-composer-*.png`, `qa/codex-02-my-work-inbox-*.png`, `qa/codex-03-inline-approval-*.png`, `qa/codex-04-approval-resolved-*.png`, `qa/codex-05-plan-card-*.png`, and `qa/codex-06-thread-running-*.png` at 1440×1024 and 1100×800. The earlier new-task design set is captured in `qa/task-create-define.png`, `qa/task-plan-generating.png`, `qa/task-plan-review.png`, `qa/task-plan-review-code.png`, and `qa/task-started.png`. The management design set is captured in `qa/manage-models.png`, `qa/manage-skills.png`, `qa/manage-plugins.png`, `qa/manage-agents.png`, `qa/manage-create-agent.png`, and `qa/manage-compact-1100.png`. Login and workspace-context evidence is captured in `qa/login-screen.png`, `qa/settings-popup-account.png`, and `qa/settings-popup-workspace.png`. The redesigned Conversation detail is captured in `qa/session-detail-redesign-1565.png` and `qa/session-detail-redesign-1100.png`; its competitive references are `qa/reference-codex-app-session-focused.png` and `qa/reference-copilot-app-session.png`. Design comparison evidence and the final QA verdict live in [`design-qa.md`](design-qa.md) and `qa/`.
