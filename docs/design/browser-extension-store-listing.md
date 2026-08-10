# Chrome Web Store Listing — MemStack Browser Bridge

Draft store listing copy, permission justifications, privacy practices, and
packaging/review notes for publishing the MV3 extension in
`agi-stack/apps/browser-extension`.

Pinned extension ID (manifest `key`): `enbljdpbhdllbbkcjhccmbgpkfmcdkkl`.

---

## 中文商店文案

- **名称**:MemStack Browser Bridge
- **简短描述**(132 字符以内):
  让 MemStack 桌面应用读取并操作你的浏览器标签页,并在侧边栏中与智能体对话。
- **完整描述**:

  MemStack Browser Bridge 是 MemStack 桌面应用的配套扩展。安装后,MemStack
  桌面端可以通过本扩展查看和操作浏览器标签页(由你发起的任务驱动),并
  在浏览器侧边栏中提供与本地智能体的聊天入口。

  主要功能:

  - 侧边栏聊天:点击工具栏图标即可打开侧边栏,与运行在你电脑上的
    MemStack 智能体对话。
  - 标签页协同:桌面应用在执行任务时可读取页面内容、创建/关闭标签页并
    整理标签分组。
  - 本地优先:所有数据都保存在你自己的电脑上,扩展不连接任何第三方
    服务器,不收集任何遥测数据。

  本扩展需要配合 MemStack 桌面应用使用,单独安装无法工作。

- **类别建议**:生产力工具(Productivity)
- **语言**:中文(简体)、English

## English store copy

- **Name**: MemStack Browser Bridge
- **Short description** (max 132 chars):
  Lets the MemStack desktop app read and drive your browser tabs, with an
  agent chat side panel.
- **Full description**:

  MemStack Browser Bridge is the companion extension for the MemStack desktop
  app. Once installed, the desktop app can read and drive your browser tabs
  (only as part of tasks you start), and a side panel gives you a chat
  interface to the agent running on your own machine.

  Highlights:

  - Side panel chat: click the toolbar icon to chat with your local MemStack
    agent without leaving the page you are on.
  - Tab automation: the desktop app can read page content, open/close tabs,
    and organize tab groups while working on your tasks.
  - Local-first: all data stays on your computer. The extension talks only to
    the MemStack desktop app on your machine and collects no telemetry.

  This extension requires the MemStack desktop app; it does nothing on its
  own.

- **Category suggestion**: Productivity
- **Languages**: English, 中文(简体)

---

## Permission justifications (for review)

| Permission | Justification |
|---|---|
| `debugger` | The desktop app drives tabs through the Chrome DevTools Protocol (page snapshots, input dispatch) when executing user-initiated agent tasks. Debuggers are attached on demand and all sessions are torn down the moment the connection to the desktop app drops. |
| `<all_urls>` (host permission) | Two uses: (1) CDP automation must work on whatever page the user's task touches, with no fixed origin list; (2) the service worker calls the local desktop API (`http://127.0.0.1:<port>`) for the side panel chat, which requires host permissions to bypass CORS. No remote server is ever contacted. |
| `nativeMessaging` | The extension's only external channel: it exchanges JSON-RPC messages with the MemStack desktop app's native messaging host (`com.memstack.browserbridge`) registered by the desktop installer. |
| `tabGroups` | Agent tasks group the tabs they create so users can see and clean up automation-driven tabs at a glance. |
| `scripting` | Injects the virtual-cursor and page-monitor content scripts into tabs that a task is actively driving. |
| `sidePanel` | Renders the chat UI in Chrome's side panel when the user clicks the toolbar action. |
| `alarms` | Schedules reconnect retries (30s periodic + ~5s fast retry) when the connection to the desktop app drops. |
| `storage` | Persists the native-connection status, the tab-group registry, and the side panel session (`storage.session`, memory-scoped). |
| `tabs` | Lists, creates, focuses, and closes tabs on behalf of desktop-app tasks. |

## Privacy practices (draft)

- **Data collection**: none. The extension collects no personal information,
  no browsing history for its own purposes, and no telemetry of any kind.
- **Data flow**: page content and tab metadata travel exclusively between the
  browser and the MemStack desktop app on the same machine, over Chrome
  native messaging (stdin/stdout pipe) and loopback HTTP/WS to
  `127.0.0.1`. Nothing is transmitted to any third-party server.
- **Credentials**: the side panel chat credential is minted by the desktop
  app, kept in `chrome.storage.session` (memory only, cleared with the
  browser session), and the long-term secrets live in the desktop app's
  encrypted vault — never in the extension.
- **Remote code**: the extension loads no remote code; all JavaScript ships
  in the package.

## Packaging

```bash
cd agi-stack/apps/browser-extension
pnpm install
pnpm build            # emits .output/chrome-mv3
cd .output && zip -r ../../memstack-browser-bridge.zip chrome-mv3
```

Upload `memstack-browser-bridge.zip` in the Chrome Web Store developer
dashboard. Verify before uploading that `.output/chrome-mv3/manifest.json`
contains the pinned `key` so the store-derived extension ID matches
`enbljdpbhdllbbkcjhccmbgpkfmcdkkl`.

## Key-retention policy

Chrome derives the store extension ID from the upload key, not from the
manifest `key` field. The desktop app's native messaging host manifest
whitelists `chrome-extension://enbljdpbhdllbbkcjhccmbgpkfmcdkkl/` in
`allowed_origins`, so:

- The `.pem` upload key generated on first publish MUST be retained securely
  (password manager / secrets vault) and reused for every update.
- Losing the key means a new extension ID, which breaks native messaging for
  all installed desktop clients until a desktop release updates
  `allowed_origins`. Treat key loss as a coordinated extension + desktop
  release.
- Local/CI builds keep the manifest `key` (see `wxt.config.ts`) so
  developer-mode installs resolve to the same ID as the store build.

## Review expectations

- `debugger` + `<all_urls>` is a heavily scrutinized combination; expect at
  least one review round asking for a screencast. Prepare a short video:
  install desktop app → agent task drives a tab with the visible virtual
  cursor → disconnect killswitch detaches everything.
- Justification text above should be pasted into the dashboard's
  per-permission fields verbatim; keep it in sync with this file when
  permissions change.
- MV3 service worker: reviewers may test that the extension works after the
  SW is restarted (`chrome://serviceworker-internals` → Stop). The SW is
  stateless across restarts except `storage.session` cache misses, which
  trigger a transparent session re-mint.
