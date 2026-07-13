# Login, workspace context, and Settings audit

## Scope

Prototype flow: unauthenticated entry → Workspace SSO or email sign-in → mission-control shell → independent Settings window → Tenant selection → Project selection → apply context → account sign-out.

## Journey health

| Step | Status | Evidence | Result |
| --- | --- | --- | --- |
| Login entry | Healthy | `qa/login-screen.png`, `qa/login-screen-1100.png` | SSO and email paths are visually distinct and preserve the desktop product language. |
| Form validation | Healthy | Browser interaction | Invalid email or a password shorter than six characters produces an inline localized alert. |
| Session restore | Healthy for prototype scope | Browser reload interaction | Trusted-device mode restores the local mock session without persisting a password. |
| Settings entry | Healthy | `qa/settings-popup-account.png` | Global rail and profile shortcuts open a modal window over the current workspace. |
| Tenant selection | Healthy | `qa/settings-popup-workspace.png` | Current context and all eligible tenants are visible before committing a change. |
| Project selection | Healthy | Browser interaction | The project list is derived from the selected tenant, preventing invalid cross-tenant combinations. |
| Context apply | Healthy | Browser interaction | Apply updates both sidebar context and Projects landing, then closes Settings. |
| Compact window | Healthy | `qa/settings-popup-workspace-1100.png`, `qa/login-screen-1100.png` | 1100×800 has no horizontal overflow; the primary CTA stays reachable. |
| Sign out | Healthy | Browser interaction | Profile and Account actions clear the mock session and return to Login. |

## Findings resolved

- P1: Settings previously replaced the entire mission-control workspace. It now opens as an independent, dismissible modal and preserves the underlying task context.
- P1: The prototype had no authentication boundary or logout path. It now includes SSO/email entry, validation, trusted-session restore, Account settings, and sign out.
- P1: Tenant and Project were shown as unrelated navigation labels. Settings → Workspace now uses an explicit two-step parent/child selection with a single apply boundary.
- P2: The first context-switch implementation updated sidebar labels but left the user on a stale task view. Applying a context now closes Settings and opens the selected Project landing.

## Production handoff boundaries

- Replace mock session persistence with the desktop authentication broker and secure OS credential storage.
- Load Tenant membership and Project authorization from the backend; never trust client catalog data for access control.
- Make context switching an authenticated server operation with failure recovery and audit events.
- Complete screen-reader and native-window testing in the packaged macOS and Windows clients.
