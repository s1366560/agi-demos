---
name: mcp-app-workflow
description: Complete workflow for creating, building, and registering MCP Apps with interactive UIs. Use when the user wants to build a new MCP App from scratch, needs step-by-step guidance through the full development cycle (setup → code → build → register → test), or asks "how to create an MCP app end-to-end". For SDK-specific patterns and API details, see the create-mcp-app skill.
---

# MCP App Workflow

Complete workflow for creating MCP Apps from project setup to server registration and testing.

## Workflow Overview

```
1. Initialize Project → 2. Implement Server → 3. Build UI → 4. Bundle → 5. Register → 6. Test
```

## Step 1: Project Initialization

Create a new project directory with proper dependencies:

```bash
mkdir my-mcp-app && cd my-mcp-app
npm init -y
npm install @modelcontextprotocol/sdk @modelcontextprotocol/ext-apps zod
npm install -D typescript tsx vite vite-plugin-singlefile
```

Create configuration files:

**tsconfig.json:**
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "esModuleInterop": true,
    "strict": true,
    "skipLibCheck": true,
    "outDir": "./dist"
  },
  "include": ["*.ts", "src/**/*.ts", "src/**/*.tsx"]
}
```

**vite.config.ts:**
```typescript
import { defineConfig } from 'vite';
import { vitePluginSinglefile } from 'vite-plugin-singlefile';

export default defineConfig({
  plugins: [vitePluginSinglefile()],
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: 'mcp-app.html',
      output: { entryFileNames: 'mcp-app.html' }
    }
  }
});
```

**package.json scripts:**
```json
{
  "scripts": {
    "build": "vite build",
    "serve": "tsx server.ts"
  }
}
```

## Step 2: Server Implementation

Create `server.ts` with tool and resource registration:

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerAppTool, registerAppResource } from "@modelcontextprotocol/ext-apps";
import { z } from "zod";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const server = new McpServer({ name: "my-app-server", version: "1.0.0" });

// Register tool
registerAppTool(server, "my_tool", {
  title: "My Tool",
  description: "Tool description",
  argsSchema: { param1: z.string().optional() },
  _meta: { ui: { resourceUri: "app://my-app/mcp-app.html" } },
}, async (args, context) => {
  return {
    content: [
      { type: "text", text: JSON.stringify({ result: "success", args }) },
      { type: "resource", resourceUri: "app://my-app/mcp-app.html" }
    ]
  };
});

// Register resource (serves bundled HTML)
registerAppResource(server, "app://my-app/mcp-app.html", async () => {
  const html = readFileSync(join(__dirname, "dist", "mcp-app.html"), "utf-8");
  return { contents: [{ uri: "app://my-app/mcp-app.html", mimeType: "text/html", text: html }] };
});

// Start server
const transport = new StdioServerTransport();
await server.connect(transport);
```

## Step 3: UI Implementation

Create `mcp-app.html` with vanilla JS (see asset template for complete example):

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <script type="module">
    import { App } from "@modelcontextprotocol/ext-apps";
    
    const app = new App({ name: "My App", version: "1.0.0" });
    
    // Register handlers BEFORE connect
    app.ontoolinput = (params) => {
      console.log("Tool input:", params.arguments);
      render(params.arguments);
    };
    
    app.ontoolresult = (result) => {
      console.log("Tool result:", result);
    };
    
    app.onhostcontextchanged = (ctx) => {
      if (ctx.theme) document.documentElement.className = ctx.theme;
    };
    
    app.onteardown = async () => ({});
    
    await app.connect();
    
    function render(data) {
      // Update UI with data
    }
  </script>
</head>
<body>
  <!-- UI content -->
</body>
</html>
```

## Step 4: Build and Bundle

Build the UI to create a single bundled HTML file:

```bash
npm run build
```

This produces `dist/mcp-app.html` with all JS/CSS inlined.

## Step 5: Register Server

Use the `register_mcp_server` tool to register the running server:

```
server_name: "my-app-server"
server_type: "stdio"
command: "npx"
args: ["tsx", "server.ts"]
```

The server must be running for registration to work.

## Step 6: Test

Call the registered tool to verify the UI renders correctly:

```
Call my_tool with param1="test"
```

The Canvas panel should display the interactive UI.

## Common Issues

| Issue | Solution |
|-------|----------|
| `Cannot find module` | Run `npm install` to install dependencies |
| `dist/mcp-app.html not found` | Run `npm run build` before starting server |
| UI not rendering | Check tool returns `resourceUri` matching resource |
| Handlers not firing | Register handlers BEFORE `app.connect()` |
| Styles not applying | Use host CSS variables: `var(--color-text-primary)` |

## Asset Template

See `assets/project_template/` for a complete working project structure.
