import { memo, useId, useState, type ComponentType } from "react";

import {
  CheckCircledIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleIcon,
  CrossCircledIcon,
  UpdateIcon,
} from "@radix-ui/react-icons";

import { useI18n } from "../../i18n";
import {
  todoChecklistStats,
  type TodoChecklistItem,
  type TodoChecklistStatus,
} from "./todoChecklistModel";

import "./TaskChecklist.css";

function TodoBanIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="m4.9 4.9 14.2 14.2" />
    </svg>
  );
}

const STATUS_ICON: Record<TodoChecklistStatus, ComponentType> = {
  pending: CircleIcon,
  in_progress: UpdateIcon,
  completed: CheckCircledIcon,
  failed: CrossCircledIcon,
  cancelled: TodoBanIcon,
};

const STATUS_LABEL_KEY: Record<TodoChecklistStatus, string> = {
  pending: "chat.todoChecklist.status.pending",
  in_progress: "chat.todoChecklist.status.inProgress",
  completed: "chat.todoChecklist.status.completed",
  failed: "chat.todoChecklist.status.failed",
  cancelled: "chat.todoChecklist.status.cancelled",
};

const TaskChecklistRow = memo<{ item: TodoChecklistItem }>(({ item }) => {
  const { t } = useI18n();
  const Icon = STATUS_ICON[item.status];
  const isActive = item.status === "in_progress";
  const statusLabel = t(STATUS_LABEL_KEY[item.status]);
  return (
    <li
      className={`task-checklist-item status-${item.status}${isActive ? " is-active" : ""}`}
    >
      <span className="task-checklist-icon" role="img" aria-label={statusLabel}>
        <Icon />
      </span>
      <span className="task-checklist-item-content">{item.content}</span>
      <span className="task-checklist-status">{statusLabel}</span>
    </li>
  );
});

TaskChecklistRow.displayName = "TaskChecklistRow";

export type TaskChecklistProps = {
  items: TodoChecklistItem[];
};

/**
 * Collapsible task checklist panel for the conversation view. Hidden when the
 * agent has not written any todos. The progress header stays visible when the
 * item list is collapsed, mirroring the web right-panel summary.
 */
export const TaskChecklist = memo<TaskChecklistProps>(({ items }) => {
  const { t } = useI18n();
  const contentId = useId();
  const [expanded, setExpanded] = useState(true);
  if (items.length === 0) return null;

  const stats = todoChecklistStats(items);
  const title = t("chat.todoChecklist.title");

  return (
    <section className="task-checklist" aria-label={title}>
      <button
        type="button"
        className="task-checklist-header"
        aria-expanded={expanded}
        aria-controls={contentId}
        aria-label={t(expanded ? "chat.collapseItem" : "chat.expandItem", {
          item: title,
        })}
        title={t(expanded ? "chat.collapseItem" : "chat.expandItem", {
          item: title,
        })}
        onClick={() => setExpanded((current) => !current)}
      >
        {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        <span className="task-checklist-title">{title}</span>
        <span className="task-checklist-count">
          {t("chat.todoChecklist.completedSummary", {
            completed: stats.completed,
            total: stats.total,
          })}
        </span>
        {stats.active > 0 ? (
          <span className="task-checklist-active">
            {t("chat.todoChecklist.activeSummary", { count: stats.active })}
          </span>
        ) : null}
      </button>
      <div
        className="task-checklist-progress"
        role="progressbar"
        aria-valuenow={stats.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t("chat.todoChecklist.progressAria")}
      >
        <div
          className="task-checklist-progress-fill"
          style={{ transform: `scaleX(${stats.percent / 100})` }}
        />
      </div>
      <div id={contentId} className="task-checklist-body" hidden={!expanded}>
        <ul className="task-checklist-items">
          {items.map((item) => (
            <TaskChecklistRow key={item.id} item={item} />
          ))}
        </ul>
      </div>
    </section>
  );
});

TaskChecklist.displayName = "TaskChecklist";

export default TaskChecklist;
