import type { ToolResultPresentationV2 } from "@agistack/plugin-slots";
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
  summary,
}: Readonly<{
  kind: ToolCallPresentationKind;
  output: unknown;
  details?: unknown;
  summary?: string;
}>): ToolResultPresentationV2 {
  return kind === "computer_use"
    ? computerUseResultPresentationV2(output, summary)
    : projectToolResultPresentationV2(
        details,
        output === undefined ? "" : detectPayloadLanguage(output).code,
        summary,
      );
}
