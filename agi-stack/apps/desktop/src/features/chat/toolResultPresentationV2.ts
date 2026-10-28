import {
  validateReplOutputPresentationV2,
  type ToolResultPresentationV2,
} from "@agistack/plugin-slots";

const MAX_TEXT = 32_768;
const text = (value: string) => value.slice(0, MAX_TEXT);

/** Accept only the declared presentation schema; never forward the raw result envelope. */
export function projectToolResultPresentationV2(
  presentation: unknown,
  visibleText: string,
  summary?: string,
): ToolResultPresentationV2 {
  if (
    presentation &&
    typeof presentation === "object" &&
    !Array.isArray(presentation)
  ) {
    const value = presentation as Record<string, unknown>;
    const repl = validateReplOutputPresentationV2(value);
    if (repl) return repl;
    if (
      value.kind === "computer_use" &&
      typeof value.app === "string" &&
      typeof value.text === "string" &&
      typeof value.summary === "string"
    )
      return Object.freeze({
        kind: "computer_use",
        app: text(value.app),
        text: text(value.text),
        summary: text(value.summary),
        ...(typeof value.screenshotArtifactId === "string" &&
        /^cua-image-[0-9a-f-]+$/u.test(value.screenshotArtifactId)
          ? { screenshotArtifactId: value.screenshotArtifactId }
          : {}),
        ...(typeof value.appIconArtifactId === "string" &&
        /^cua-image-[0-9a-f-]+$/u.test(value.appIconArtifactId)
          ? { appIconArtifactId: value.appIconArtifactId }
          : {}),
        ...(typeof value.windowId === "string"
          ? { windowId: value.windowId.slice(0, 256) }
          : {}),
        ...(typeof value.windowTitle === "string"
          ? { windowTitle: value.windowTitle.slice(0, 256) }
          : {}),
        ...(typeof value.observedAt === "string"
          ? { observedAt: value.observedAt.slice(0, 64) }
          : {}),
      });
    if (value.kind === "text" && typeof value.text === "string")
      return Object.freeze({ kind: "text", text: text(value.text) });
    if (value.kind === "summary" && typeof value.summary === "string")
      return Object.freeze({ kind: "summary", summary: text(value.summary) });
    if (
      value.kind === "diff" &&
      typeof value.before === "string" &&
      typeof value.after === "string"
    )
      return Object.freeze({
        kind: "diff",
        before: text(value.before),
        after: text(value.after),
        ...(typeof value.language === "string"
          ? { language: value.language.slice(0, 64) }
          : {}),
      });
    if (
      value.kind === "table" &&
      Array.isArray(value.columns) &&
      value.columns.every((cell) => typeof cell === "string") &&
      Array.isArray(value.rows) &&
      value.rows.every(
        (row) =>
          Array.isArray(row) &&
          row.length === (value.columns as unknown[]).length &&
          row.every((cell) => typeof cell === "string"),
      )
    ) {
      return Object.freeze({
        kind: "table",
        columns: Object.freeze(
          value.columns.slice(0, 32).map((cell) => text(cell)),
        ),
        rows: Object.freeze(
          value.rows
            .slice(0, 100)
            .map((row: string[]) =>
              Object.freeze(
                row.slice(0, 32).map((cell) => cell.slice(0, 1024)),
              ),
            ),
        ),
      });
    }
  }
  return summary
    ? Object.freeze({ kind: "summary", summary: text(summary) })
    : Object.freeze({ kind: "text", text: text(visibleText) });
}
