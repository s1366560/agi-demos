/**
 * The pinned messages of a transcript: a collapsible list above the messages,
 * with a way to jump to each one and to unpin it.
 */

import { useId, useState } from "react";

import { useTranslation } from "react-i18next";

import { ChevronDown, ChevronUp, Pin, PinOff } from "lucide-react";

export interface PinnedMessage {
  id: string;
  content: string;
}

export function PinnedMessages({
  pinned,
  onJump,
  onUnpin,
}: {
  pinned: readonly PinnedMessage[];
  onJump: (id: string) => void;
  onUnpin: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const sectionId = useId();
  if (pinned.length === 0) return null;
  return (
    <div className="flex-shrink-0 border-b border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-800/50">
      <button
        type="button"
        onClick={() => {
          setCollapsed(!collapsed);
        }}
        aria-expanded={!collapsed}
        aria-controls={sectionId}
        className="flex items-center gap-2 w-full px-4 py-2 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700/50 active:bg-slate-200 dark:active:bg-slate-700/70 transition-colors duration-150 motion-reduce:transition-none min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
      >
        <Pin size={12} />
        <span>{t("agent.pinnedMessages", "Pinned")}</span>
        <span className="text-slate-400">({pinned.length})</span>
        <span className="ml-auto">
          {collapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
        </span>
      </button>
      {!collapsed && (
        <div
          id={sectionId}
          className="px-4 pb-2 space-y-1.5 max-h-40 overflow-y-auto"
        >
          {pinned.map((message) => (
            <div
              key={`pinned-${message.id}`}
              className="flex items-start gap-2 px-3 py-2 bg-white dark:bg-slate-800 rounded-lg border border-slate-200/80 dark:border-slate-700/50 transition-colors group/pin hover:bg-slate-100 dark:hover:bg-slate-700/60"
            >
              <button
                type="button"
                onClick={() => {
                  onJump(message.id);
                }}
                className="flex-1 min-w-0 text-left rounded-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                aria-label={t("agent.actions.jumpToMessage", "Jump to message")}
              >
                <p className="text-xs text-slate-600 dark:text-slate-300 line-clamp-2 leading-relaxed">
                  {message.content || "…"}
                </p>
              </button>
              <button
                type="button"
                onClick={() => {
                  onUnpin(message.id);
                }}
                className="touch-target flex-shrink-0 p-1.5 rounded-md text-slate-400 hover:text-red-500 active:text-red-600 opacity-100 md:opacity-0 md:group-hover/pin:opacity-100 md:group-focus-within/pin:opacity-100 transition-[color,opacity] duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                aria-label={t("agent.actions.unpin", "Unpin")}
              >
                <PinOff size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
