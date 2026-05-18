# Sandbox MCP Server Docs

Last checked against repository docs: 2026-05-18.

## Maintained Entry Points

| Document | Purpose |
|---|---|
| [../README.md](../README.md) | Quick start and current server overview. |
| [../DEPLOYMENT.md](../DEPLOYMENT.md) | Deployment guide. |
| [../MIGRATION.md](../MIGRATION.md) | Migration guide. |
| [../PERFORMANCE.md](../PERFORMANCE.md) | Performance notes. |
| [../TROUBLESHOOTING.md](../TROUBLESHOOTING.md) | Troubleshooting guide. |

## Historical Phase Records

Most files in this directory are phase outputs for the XFCE/TigerVNC migration. They are
kept for audit history and should not override the root README or current code.

| Cluster | Files |
|---|---|
| XFCE migration | `xfce-*.md`, `phase*-completion.md`, `phase*-changes.md` |
| TigerVNC migration | `TIGERVNC_*.md`, `phase3-tigervnc-*.md` |
| Testing reports | `phase4-xfce-testing.md`, `TIGERVNC_DOCKER_TEST_REPORT.md`, `xfce-docker-test-summary.md` |
| Planning | `remote-desktop-plan.md`, `TIGERVNC_TDD_PLAN.md`, `xfce-tdd-workflow.md` |

When updating sandbox behavior, update the root docs first and add a dated historical note
only when the rationale needs to be preserved.
