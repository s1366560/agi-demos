# MemStack Desktop — My Work Mission Control

Interactive high-fidelity prototype for the selected desktop-client direction. It demonstrates one shared task kernel across two capability modes:

- **Work:** research, source lineage, executive brief artifacts, human input, review, and steering.
- **Code:** isolated worktree execution, plan/changes/terminal/preview tabs, approval boundaries, verification, and editor handoff.
- **Settings → AI resources:** Models uses a Provider-first flow for authentication, endpoint verification, model discovery, model enablement, and workspace routing. Skills, Plugins, and Agents retain the governed catalog/detail pattern with specialized dependency, permission, validation, and audit views.
- **Identity and workspace context:** Sign in with workspace SSO or email, restore a trusted local prototype session, sign out from the account menu, and switch Tenant → Project from Settings → Workspace.
- **Independent Settings window:** Account, workspace context, preferences, and AI resources open in a focused modal window without replacing the task workspace underneath.
- **Internationalization:** English and Simplified Chinese can be switched instantly from Settings → General and the preference is persisted locally.

## Core interactions

- Switch Work / Code in the lower-left mode control.
- Create a task, let the agent generate a plan, edit or trim that plan, and explicitly approve execution.
- Select tasks across Needs input, Running, and Ready to review groups.
- Open and complete the approval/input dialog.
- Pause and resume the active run.
- Review sources or code changes next to the artifact.
- Use artifact tabs and the steering composer.
- Navigate Home, My Work, Automations, Search, and Projects.
- Sign in, open Account settings from the profile menu, choose a Tenant and then one of its Projects, and apply the new workspace context.
- Open Settings → Models to test Provider connection, manual Model ID, routing, and the three-step Add Provider wizard. Switch between the other AI resources or change the interface language under General.
- Search and filter resource catalogs, select records, switch detail tabs, and save model/agent/skill configuration drafts.
- Run skill validation, install/update/disable plugins, pause/enable agents, and create governed resource drafts.

## Local preview

```bash
npm install
npm run dev
```

The production bundle is verified with `npm run build`. The new-task design set is captured in `qa/task-create-define.png`, `qa/task-plan-generating.png`, `qa/task-plan-review.png`, `qa/task-plan-review-code.png`, and `qa/task-started.png`. The management design set is captured in `qa/manage-models.png`, `qa/manage-skills.png`, `qa/manage-plugins.png`, `qa/manage-agents.png`, `qa/manage-create-agent.png`, and `qa/manage-compact-1100.png`. Login and workspace-context evidence is captured in `qa/login-screen.png`, `qa/settings-popup-account.png`, and `qa/settings-popup-workspace.png`. Design comparison evidence and the final QA verdict live in [`design-qa.md`](design-qa.md) and `qa/`.
