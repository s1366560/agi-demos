// The shell opens an MCP app in its canvas, which the isolated page does not have.
// The tool step cards of the page therefore get a hook that does nothing instead of
// the one that reads the shell's canvas, project and MCP app state.
import type { MouseEvent } from "react";

export const useMCPAppOpen =
  () => (_event: MouseEvent<HTMLButtonElement>) => {};
