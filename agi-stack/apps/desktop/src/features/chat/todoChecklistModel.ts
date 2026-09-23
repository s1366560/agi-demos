import type { AgentTimelineItem } from "../../types";

import { exactToolResults } from "./timelineExecutionIdentity";
import { timelineToolResultFailed } from "./toolResultStatus";

// Pure presentation logic for the agent task checklist (web parity: audit
// §1.6 — web TaskList.tsx + ExecutionTimeline todowrite summarization). Kept
// free of React/JSX so the node:test harness can compile and exercise it
// directly (see tests/todo-checklist-model.test.mjs).

export type TodoChecklistStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

export type TodoChecklistPriority = "high" | "medium" | "low";

export type TodoChecklistItem = {
  id: string;
  content: string;
  status: TodoChecklistStatus;
  priority: TodoChecklistPriority;
  orderIndex: number;
};

export type TodoChecklistStats = {
  total: number;
  completed: number;
  failed: number;
  active: number;
  percent: number;
};

export type TodoSummaryStatus = TodoChecklistStatus | "blocked";

export type TodoToolCallSummary = {
  kind: "read" | "write";
  verb: "add" | "update" | "replace" | "write" | null;
  total: number;
  statusCounts: Array<{ status: TodoSummaryStatus; count: number }>;
  titles: string[];
  hiddenTitleCount: number;
  todoId: string | null;
};

type TranslateFn = (
  key: string,
  values?: Record<string, string | number>,
) => string;

/** Todo tools arrive under several spellings across providers and history. */
export function isTodoToolName(toolName: string | null | undefined): boolean {
  return (
    typeof toolName === "string" && toolName.toLowerCase().includes("todo")
  );
}

function normalizeTodoStatus(value: unknown): TodoChecklistStatus {
  const status = typeof value === "string" ? value.trim().toLowerCase() : "";
  switch (status) {
    case "in_progress":
    case "in-progress":
    case "running":
      return "in_progress";
    case "completed":
    case "complete":
    case "done":
      return "completed";
    case "failed":
    case "error":
      return "failed";
    case "cancelled":
    case "canceled":
      return "cancelled";
    default:
      return "pending";
  }
}

/** Summary buckets keep web's extra "blocked" label instead of folding it. */
function normalizeTodoSummaryStatus(value: unknown): TodoSummaryStatus {
  const status = typeof value === "string" ? value.trim().toLowerCase() : "";
  return status === "blocked" ? "blocked" : normalizeTodoStatus(value);
}

function normalizeTodoPriority(value: unknown): TodoChecklistPriority {
  return value === "high" || value === "low" ? value : "medium";
}

function readTaskContent(record: Record<string, unknown>): string | null {
  // Web TaskList reads AgentTask.content; todowrite payloads have used title /
  // task / description / name spellings (web ExecutionTimeline getTodoTitle).
  for (const key of ["content", "title", "task", "description", "name"]) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function readOrderIndex(value: unknown): number | null {
  return Number.isInteger(value) && (value as number) >= 0
    ? (value as number)
    : null;
}

function normalizeTaskRecords(values: unknown[]): TodoChecklistItem[] {
  const byId = new Map<string, TodoChecklistItem>();
  values.forEach((value, sourceIndex) => {
    if (!isRecord(value)) return;
    const content = readTaskContent(value);
    if (!content) return;
    const id =
      typeof value.id === "string" && value.id.trim()
        ? value.id.trim()
        : `task-${sourceIndex + 1}`;
    byId.set(id, {
      id,
      content,
      status: normalizeTodoStatus(value.status),
      priority: normalizeTodoPriority(value.priority),
      orderIndex:
        readOrderIndex(value.order_index ?? value.orderIndex) ?? sourceIndex,
    });
  });
  return [...byId.values()].sort(
    (left, right) =>
      left.orderIndex - right.orderIndex || left.id.localeCompare(right.id),
  );
}

function taskListPayload(item: AgentTimelineItem): unknown[] {
  // Live events surface the list directly on the item; persisted history
  // carries it inside the payload (mirrors workPlanTimelineModel).
  if (Array.isArray(item.tasks)) return item.tasks;
  const payload = isRecord(item.payload) ? item.payload : null;
  return Array.isArray(payload?.tasks) ? payload.tasks : [];
}

function taskUpdatePatch(
  item: AgentTimelineItem,
): { id: string; status?: TodoChecklistStatus; content?: string } | null {
  const payload = isRecord(item.payload) ? item.payload : item;
  // Two wire shapes exist: { task: { id, status, content } } (runtime events)
  // and the flat { task_id, status, content } web TaskSync handler shape.
  const nested = isRecord(payload.task) ? payload.task : null;
  const id =
    (nested && typeof nested.id === "string" ? nested.id : null) ??
    (typeof payload.task_id === "string" ? payload.task_id : null);
  if (!id) return null;
  const statusSource = nested ? nested.status : payload.status;
  const contentSource = nested
    ? readTaskContent(nested)
    : readTaskContent(payload);
  const patch: { id: string; status?: TodoChecklistStatus; content?: string } =
    { id };
  if (typeof statusSource === "string")
    patch.status = normalizeTodoStatus(statusSource);
  if (contentSource) patch.content = contentSource;
  return patch;
}

/**
 * Persisted task events are authoritative. Legacy tool snapshots are accepted
 * only after execution succeeds; requested input alone is not persisted state.
 */
export function todoChecklistFromTimeline(
  items: AgentTimelineItem[],
): TodoChecklistItem[] {
  let snapshot: TodoChecklistItem[] = [];
  let sawTaskEvent = false;
  const linkedResults = exactToolResults(items);
  const callsByResult = new Map(
    items.flatMap((call) => {
      const result = linkedResults.get(call.id);
      return result ? [[result.id, call] as const] : [];
    }),
  );

  for (const item of items) {
    if (item.type === "task_list_updated") {
      sawTaskEvent = true;
      snapshot = normalizeTaskRecords(taskListPayload(item));
      continue;
    }
    if (["task_updated", "task_start", "task_complete"].includes(item.type)) {
      const patch = taskUpdatePatch(item);
      if (patch && item.type === "task_start") patch.status = "in_progress";
      if (!patch) continue;
      snapshot = snapshot.map((task) =>
        task.id === patch.id
          ? {
              ...task,
              ...(patch.status ? { status: patch.status } : {}),
              ...(patch.content ? { content: patch.content } : {}),
            }
          : task,
      );
      continue;
    }
    if (
      sawTaskEvent ||
      item.type !== "observe" ||
      timelineToolResultFailed(item)
    )
      continue;
    const call = callsByResult.get(item.id);
    if (!isTodoToolName(call?.toolName ?? item.toolName)) continue;
    const output = recordFromUnknown(item.toolOutput);
    // Empty arrays are real snapshots too (for example, after deleting all tasks).
    if (Array.isArray(output?.todos)) {
      snapshot = normalizeTaskRecords(output.todos);
      continue;
    }
    // Some historical writes acknowledge success but omit the saved snapshot.
    // Strict execution IDs associate that acknowledgement with its request.
    if (!call || output?.success !== true) continue;
    const input = recordFromUnknown(call.toolInput);
    if (!Array.isArray(input?.todos)) continue;
    if (input.action === "update" && typeof input.todo_id === "string") {
      const patch = taskUpdatePatch({
        ...item,
        payload: {
          task: {
            ...(isRecord(input.todos[0]) ? input.todos[0] : {}),
            id: input.todo_id,
          },
        },
      });
      if (patch)
        snapshot = snapshot.map((task) =>
          task.id === patch.id
            ? {
                ...task,
                ...(patch.status ? { status: patch.status } : {}),
                ...(patch.content ? { content: patch.content } : {}),
              }
            : task,
        );
    } else if (input.action === undefined || input.action === "replace") {
      snapshot = normalizeTaskRecords(input.todos);
    }
  }
  return snapshot;
}

/** Web TaskList stats: total / completed / failed / active + integer percent. */
export function todoChecklistStats(
  items: TodoChecklistItem[],
): TodoChecklistStats {
  const total = items.length;
  const completed = items.filter((item) => item.status === "completed").length;
  const failed = items.filter((item) => item.status === "failed").length;
  const active = items.filter((item) => item.status === "in_progress").length;
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
  return { total, completed, failed, active, percent };
}

const TITLE_MAX_LENGTH = 48;

function truncateMiddle(value: string, maxLength = TITLE_MAX_LENGTH): string {
  if (value.length <= maxLength) return value;
  const half = Math.floor((maxLength - 1) / 2);
  return `${value.slice(0, half)}…${value.slice(value.length - half)}`;
}

function todosFromRecord(
  record: Record<string, unknown> | null,
): Record<string, unknown>[] {
  const todos = record?.todos;
  return Array.isArray(todos)
    ? todos.filter((todo): todo is Record<string, unknown> => isRecord(todo))
    : [];
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  if (isRecord(value)) return value;
  if (typeof value === "string" && value.trim()) {
    try {
      const parsed: unknown = JSON.parse(value);
      return isRecord(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * Structured summary of a todo tool call for the timeline row title (web
 * ExecutionTimeline summarizeTodoDetails parity). Returns null for non-todo
 * tools so callers can keep the generic row text.
 */
export function todoToolCallSummary(
  call: AgentTimelineItem,
  result?: AgentTimelineItem | null,
): TodoToolCallSummary | null {
  if (!isTodoToolName(call.toolName)) return null;
  const primaryRecord = recordFromUnknown(call.toolInput);
  const fallbackRecord =
    recordFromUnknown(result?.toolOutput) ?? recordFromUnknown(call.toolOutput);
  const record = primaryRecord ?? fallbackRecord;
  const todos = todosFromRecord(record);
  const fallbackTodos = todosFromRecord(fallbackRecord);
  const todosHaveTitles = todos.some((todo) => Boolean(readTaskContent(todo)));
  const source =
    todos.length > 0 && (todosHaveTitles || fallbackTodos.length === 0)
      ? todos
      : fallbackTodos;

  const action =
    typeof record?.action === "string"
      ? record.action.trim().toLowerCase()
      : "";
  const todoId = typeof record?.todo_id === "string" ? record.todo_id : null;

  const statusCounts = new Map<TodoSummaryStatus, number>();
  for (const todo of source) {
    const status = normalizeTodoSummaryStatus(todo.status);
    statusCounts.set(status, (statusCounts.get(status) ?? 0) + 1);
  }

  const titles = source
    .map((todo) => readTaskContent(todo))
    .filter((title): title is string => Boolean(title))
    .map((title) => truncateMiddle(title));

  const kind = call.toolName?.toLowerCase().includes("read") ? "read" : "write";
  const verb =
    kind === "read"
      ? null
      : action === "add"
        ? "add"
        : action === "update"
          ? "update"
          : action === "replace"
            ? "replace"
            : "write";

  return {
    kind,
    verb,
    total: source.length,
    statusCounts: [...statusCounts.entries()]
      .slice(0, 3)
      .map(([status, count]) => ({ status, count })),
    titles: titles.slice(0, 2),
    hiddenTitleCount: Math.max(0, titles.length - 2),
    todoId,
  };
}

const SUMMARY_LIST_SEPARATOR = ", ";
const SUMMARY_DETAIL_SEPARATOR = ": ";

function summaryStatusLabel(status: TodoSummaryStatus, t: TranslateFn): string {
  switch (status) {
    case "completed":
      return t("chat.todo.status.completed");
    case "in_progress":
      return t("chat.todo.status.inProgress");
    case "blocked":
      return t("chat.todo.status.blocked");
    case "cancelled":
      return t("chat.todo.status.cancelled");
    case "failed":
      return t("chat.todo.status.failed");
    default:
      return t("chat.todo.status.pending");
  }
}

/** Localized one-line title for a todo tool-call row (web format). */
export function formatTodoToolCallSummary(
  summary: TodoToolCallSummary,
  t: TranslateFn,
): string {
  const statusText = summary.statusCounts
    .map(({ status, count }) =>
      t("chat.todo.statusCount", {
        count,
        status: summaryStatusLabel(status, t),
      }),
    )
    .join(SUMMARY_LIST_SEPARATOR);
  const visibleTitles = summary.titles.join(SUMMARY_LIST_SEPARATOR);
  const titleText = visibleTitles
    ? `${visibleTitles}${
        summary.hiddenTitleCount > 0
          ? t("chat.todo.moreItems", { count: summary.hiddenTitleCount })
          : ""
      }`
    : "";
  const suffix = [statusText, titleText]
    .filter(Boolean)
    .join(SUMMARY_DETAIL_SEPARATOR);

  if (summary.kind === "read") {
    return summary.total > 0
      ? t("chat.todo.readMany", { count: summary.total, summary: suffix })
      : t("chat.todo.read");
  }

  const verb = t(`chat.todo.verb.${summary.verb ?? "write"}`);
  if (summary.total > 0) {
    return t("chat.todo.writeMany", {
      verb,
      count: summary.total,
      summary: suffix,
    });
  }
  if (summary.todoId)
    return t("chat.todo.writeOne", { verb, id: summary.todoId });
  return t("chat.todo.write", { verb });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
