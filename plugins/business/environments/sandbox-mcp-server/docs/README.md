# Sandbox MCP Server Docs

Last checked against repository docs: 2026-06-23.

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

> **Note on TigerVNC → KasmVNC**: The TigerVNC + noVNC + websockify stack documented in the
> historical files above has since been replaced by a KasmVNC-centric runtime path
> (built-in web client on port 6080, KDE Plasma 5.27 on Ubuntu 24.04 LTS). Some orchestration still accepts
> a `VNC_SERVER_TYPE`/`VNC` compatibility flag for older commands, but current behavior should
> be verified against KasmVNC. The above phase records are retained only for
> audit history; for the current remote-desktop behavior, see the "Remote Desktop" / "VNC Server"
> sections of [../README.md](../README.md) and the `KasmVNC` build steps in [../Dockerfile](../Dockerfile).

When updating sandbox behavior, update the root docs first and add a dated historical note
only when the rationale needs to be preserved.
