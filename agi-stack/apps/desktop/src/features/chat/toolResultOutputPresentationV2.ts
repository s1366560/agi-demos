import {
  projectReplOutputPresentationV2,
  validateReplOutputPresentationV2,
  type ToolResultPresentationV2,
} from "@agistack/plugin-slots";
import {
  detectPayloadLanguage,
  type ToolCallPresentationKind,
} from "./chatTimelineModel";
import { computerUseResultPresentationV2 } from "./computerUseResultPresentationV2";
import { projectToolResultPresentationV2 } from "./toolResultPresentationV2";

/** The timeline and inspector share one safe output projection for each declared kind. */
export function projectToolOutputPresentationV2({
  kind,
  output,
  details,
  display,
  summary,
}: Readonly<{
  kind: ToolCallPresentationKind;
  output: unknown;
  details?: unknown;
  display?: unknown;
  summary?: string;
}>): ToolResultPresentationV2 {
  if (kind === "repl_output") {
    const presentation =
      display && typeof display === "object" && "entries" in display
        ? validateReplOutputPresentationV2(display)
        : projectReplOutputPresentationV2(output, "device");
    if (presentation) return presentation;
  }
  return kind === "computer_use"
    ? computerUseResultPresentationV2(output, summary)
    : projectToolResultPresentationV2(
        details,
        output === undefined ? "" : detectPayloadLanguage(output).code,
        summary,
      );
}
