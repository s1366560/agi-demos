/**
 * MCP App Server Template
 * 
 * This server provides tools with UI resources for interactive MCP Apps.
 * Replace 'my_app' with your app name throughout.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerAppTool, registerAppResource } from "@modelcontextprotocol/ext-apps";
import { z } from "zod";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

// Get current directory for file paths
const __dirname = dirname(fileURLToPath(import.meta.url));

// Create MCP server instance
const server = new McpServer({
  name: "my-app-server",
  version: "1.0.0",
});

// Resource URI - must match the resource registration below
const RESOURCE_URI = "app://my-app/mcp-app.html";

// ============================================
// TOOL REGISTRATION
// ============================================

registerAppTool(
  server,
  "my_tool",  // Tool name - this is what the LLM calls
  {
    title: "My Tool",
    description: "Description of what this tool does. Be specific about parameters and behavior.",
    argsSchema: {
      // Define parameters using Zod
      message: z.string().optional().describe("Optional message parameter"),
      count: z.number().optional().describe("Optional count parameter"),
    },
    // Link to UI resource
    _meta: {
      ui: {
        resourceUri: RESOURCE_URI,
        visibility: ["model", "app"],  // Who can call this tool
      }
    }
  },
  async (args, context) => {
    // Tool handler - process args and return result
    const { message = "default", count = 1 } = args;
    
    // The result is passed to the UI via app.ontoolresult
    return {
      content: [
        // Text content for non-UI hosts
        {
          type: "text" as const,
          text: JSON.stringify({
            success: true,
            message,
            count,
            timestamp: new Date().toISOString()
          }, null, 2)
        },
        // Resource reference triggers UI rendering
        {
          type: "resource" as const,
          resourceUri: RESOURCE_URI
        }
      ]
    };
  }
);

// ============================================
// RESOURCE REGISTRATION
// ============================================

registerAppResource(
  server,
  RESOURCE_URI,
  async () => {
    // Read the bundled HTML file
    const htmlPath = join(__dirname, "dist", "mcp-app.html");
    const html = readFileSync(htmlPath, "utf-8");
    
    return {
      contents: [
        {
          uri: RESOURCE_URI,
          mimeType: "text/html",
          text: html
        }
      ]
    };
  }
);

// ============================================
// START SERVER
// ============================================

const transport = new StdioServerTransport();
await server.connect(transport);
