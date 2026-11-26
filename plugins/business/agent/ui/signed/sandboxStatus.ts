import { useEffect, useState } from "react";

import type { RichPageContext } from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import { invoke } from "./reviewAuthority";
import type { InteractionEvent } from "./useInteractions";

export interface ProjectSandbox {
  status?: string;
  is_healthy?: boolean;
}

// Tools that work inside the project sandbox, as the original workbench knows them.
const SANDBOX_TOOLS = new Set([
  "read",
  "write",
  "edit",
  "glob",
  "grep",
  "bash",
]);

export type SandboxConnection = "idle" | "connecting" | "connected" | "error";

/** The connection of the project sandbox, named as the original status bar names it. */
export function sandboxConnection(
  sandbox: ProjectSandbox | null | undefined,
): SandboxConnection | undefined {
  const status = sandbox?.status;
  if (!status) return "idle";
  switch (status) {
    case "pending":
    case "creating":
    case "connecting":
      return "connecting";
    case "running":
      // A sandbox that is not healthy is not a connection to rely on.
      return sandbox?.is_healthy === false ? "error" : "connected";
    case "unhealthy":
    case "disconnected":
    case "error":
      return "error";
    case "stopped":
    case "terminated":
      return "idle";
    // A state the original workbench does not know leaves the slot as it is.
    default:
      return undefined;
  }
}

/** The sandbox tool that started last and has not returned, if one is running. */
export function runningSandboxTool(
  events: readonly Pick<
    InteractionEvent,
    "type" | "toolName" | "execution_id"
  >[],
): string | undefined {
  const running = new Map<string, string>();
  for (const event of events) {
    if (
      !event.execution_id ||
      !event.toolName ||
      !SANDBOX_TOOLS.has(event.toolName)
    )
      continue;
    if (event.type === "act") running.set(event.execution_id, event.toolName);
    else if (event.type === "observe") running.delete(event.execution_id);
  }
  return [...running.values()].at(-1);
}

/**
 * The sandbox of the project, read again from time to time. A page cannot be told
 * when it changes, so it is read often while a turn runs and rarely otherwise.
 */
export function useProjectSandbox(scope: RichPageContext, running: boolean) {
  const [sandbox, setSandbox] = useState<ProjectSandbox | null>();
  useEffect(() => {
    if (!scope.commands.includes("chat-project-context")) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const row = await invoke<{ sandbox: ProjectSandbox | null }>(
          "chat-project-context",
          { view: "sandbox" },
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) setSandbox(row.sandbox);
      } catch {
        // The other slots of the bar still show.
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(refresh, running ? 3000 : 30000);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [scope, running]);
  return sandbox;
}
