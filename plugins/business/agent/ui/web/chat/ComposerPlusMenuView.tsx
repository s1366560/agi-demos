import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { Check, Loader2, Plus, Search } from "lucide-react";
type MenuSectionKey = "actions" | "plugins" | "agents" | "commands";

export interface MenuEntry {
  id: string;
  section: MenuSectionKey;
  label: string;
  description?: string | undefined;
  /** Extra search surface (e.g. category, server name) - never displayed. */
  keywords: string;
  icon: ReactNode;
  disabled?: boolean | undefined;
  /** Check state shown on the right edge (active agent, plan mode). */
  active?: boolean | undefined;
  onSelect: () => void;
}

const SECTION_ORDER: MenuSectionKey[] = [
  "actions",
  "plugins",
  "agents",
  "commands",
];

export function ComposerPlusMenuView({
  entries,
  disabled,
  isOpen,
  setIsOpen,
  extraAction,
  pluginsLoading = false,
  definitionsLoading = false,
  commandsLoading = false,
}: {
  entries: MenuEntry[];
  disabled?: boolean | undefined;
  isOpen: boolean;
  setIsOpen: React.Dispatch<React.SetStateAction<boolean>>;
  extraAction?: ReactNode;
  pluginsLoading?: boolean;
  definitionsLoading?: boolean;
  commandsLoading?: boolean;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [focusIndex, setFocusIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const itemRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

  // Reset transient state on open.
  useEffect(() => {
    if (isOpen) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setQuery("");
      setFocusIndex(0);
      // Focus after the menu is attached so autoFocus semantics apply on every open.
      requestAnimationFrame(() => {
        searchRef.current?.focus();
      });
    }
  }, [isOpen]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const closeMenu = useCallback(() => {
    setIsOpen(false);
  }, []);

  const filteredEntries = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((entry) => {
      const haystack =
        `${entry.label} ${entry.description ?? ""} ${entry.keywords}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [entries, query]);

  // Clamp keyboard focus when the filtered list shrinks.
  useEffect(() => {
    if (filteredEntries.length === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (focusIndex !== 0) setFocusIndex(0);
      return;
    }
    if (focusIndex >= filteredEntries.length) {
      setFocusIndex(filteredEntries.length - 1);
    }
  }, [filteredEntries.length, focusIndex]);

  // Scroll the focused entry into view.
  useEffect(() => {
    itemRefs.current.get(focusIndex)?.scrollIntoView({ block: "nearest" });
  }, [focusIndex]);

  const selectEntry = useCallback(
    (entry: MenuEntry) => {
      if (entry.disabled) return;
      entry.onSelect();
      closeMenu();
    },
    [closeMenu],
  );

  const handleSearchKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((prev) =>
          filteredEntries.length === 0
            ? 0
            : Math.min(prev + 1, filteredEntries.length - 1),
        );
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((prev) => Math.max(prev - 1, 0));
        return;
      }
      if (event.key === "Enter") {
        const entry = filteredEntries[focusIndex];
        if (entry) {
          event.preventDefault();
          selectEntry(entry);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
      }
    },
    [filteredEntries, focusIndex, selectEntry, closeMenu],
  );

  const sectionTitles: Record<MenuSectionKey, string> = useMemo(
    () => ({
      actions: t("agent.plusMenu.groupActions", "Actions"),
      plugins: t("agent.plusMenu.groupPlugins", "Plugins"),
      agents: t("agent.plusMenu.groupAgents", "Agents"),
      commands: t("agent.plusMenu.groupCommands", "Commands"),
    }),
    [t],
  );

  const sectionEmptyText: Partial<Record<MenuSectionKey, string>> = useMemo(
    () => ({
      plugins: pluginsLoading
        ? t("agent.plusMenu.loading", "Loading…")
        : t("agent.plusMenu.noPlugins", "No plugins available"),
      agents: definitionsLoading
        ? t("agent.plusMenu.loading", "Loading…")
        : t("agent.noAgentsAvailable", "No agents available"),
      commands: commandsLoading
        ? t("agent.plusMenu.loading", "Loading…")
        : t("agent.slashCommand.noItems", "No commands or skills available"),
    }),
    [t, pluginsLoading, definitionsLoading, commandsLoading],
  );

  let renderedIndex = -1;

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        type="button"
        onClick={() => {
          if (!disabled) setIsOpen((v) => !v);
        }}
        disabled={disabled}
        title={t("agent.plusMenu.label", "Add")}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        data-testid="composer-plus-button"
        className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
          disabled
            ? "cursor-not-allowed text-slate-300 dark:text-slate-600"
            : `text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700/50 ${
                isOpen ? "text-primary bg-primary/5" : ""
              }`
        }`}
      >
        <Plus size={18} />
      </button>

      {isOpen && (
        <div
          role="menu"
          aria-label={t("agent.plusMenu.title", "Add")}
          data-testid="composer-plus-menu"
          className="absolute bottom-full left-0 mb-2 z-50 flex w-[min(26rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-slate-200 bg-slate-50 shadow-lg shadow-slate-200/40 dark:border-slate-700 dark:bg-slate-800 dark:shadow-slate-950/20"
        >
          {/* Search */}
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-700/50">
            <Search size={14} className="shrink-0 text-slate-400" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setFocusIndex(0);
              }}
              onKeyDown={handleSearchKeyDown}
              placeholder={t(
                "agent.plusMenu.searchPlaceholder",
                "Search plugins, agents, commands…",
              )}
              aria-label={t(
                "agent.plusMenu.searchPlaceholder",
                "Search plugins, agents, commands…",
              )}
              data-testid="composer-plus-search"
              className="w-full bg-transparent text-sm text-slate-800 placeholder:text-content-tertiary focus:outline-none dark:text-slate-100"
            />
          </div>

          {/* Entries */}
          <div className="max-h-[min(24rem,50vh)] overflow-y-auto py-1">
            {filteredEntries.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-slate-400">
                {t("agent.slashCommand.noMatch", 'No matches for "{{query}}"', {
                  query,
                })}
              </div>
            ) : (
              SECTION_ORDER.map((section) => {
                const sectionEntries = filteredEntries.filter(
                  (e) => e.section === section,
                );
                if (sectionEntries.length === 0) return null;
                return (
                  <div
                    key={section}
                    role="group"
                    aria-label={sectionTitles[section]}
                  >
                    <div
                      role="presentation"
                      className="bg-slate-50/50 px-3 py-1.5 text-2xs font-semibold uppercase tracking-label text-content-tertiary dark:bg-slate-800/50"
                    >
                      {sectionTitles[section]}
                    </div>
                    {section === "actions" && extraAction && !query.trim() && (
                      <div className="px-1 py-0.5">{extraAction}</div>
                    )}
                    {sectionEntries.map((entry) => {
                      renderedIndex += 1;
                      const entryIndex = renderedIndex;
                      const isFocused = entryIndex === focusIndex;
                      return (
                        <button
                          key={entry.id}
                          ref={(el) => {
                            if (el) itemRefs.current.set(entryIndex, el);
                            else itemRefs.current.delete(entryIndex);
                          }}
                          type="button"
                          role="menuitem"
                          disabled={entry.disabled}
                          onClick={() => {
                            if (entry.disabled) return;
                            entry.onSelect();
                            closeMenu();
                          }}
                          onMouseEnter={() => {
                            setFocusIndex(entryIndex);
                          }}
                          aria-disabled={entry.disabled}
                          className={`w-full text-left px-3 py-2 flex items-center justify-between gap-2 rounded-md text-xs transition-colors duration-150 ${
                            entry.disabled
                              ? "cursor-not-allowed text-slate-300 dark:text-slate-600"
                              : "cursor-pointer"
                          } ${
                            isFocused && !entry.disabled
                              ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                              : "text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                          }`}
                        >
                          <div className="flex min-w-0 items-center gap-2.5">
                            <span className="shrink-0 text-slate-400 dark:text-slate-500">
                              {entry.icon}
                            </span>
                            <div className="flex min-w-0 flex-col">
                              <span className="truncate font-medium">
                                {entry.label}
                              </span>
                              {entry.description && (
                                <span className="truncate text-2xs text-slate-400 dark:text-slate-500">
                                  {entry.description}
                                </span>
                              )}
                            </div>
                          </div>
                          {entry.active && (
                            <Check
                              size={16}
                              className="shrink-0 text-blue-600 dark:text-blue-400"
                            />
                          )}
                        </button>
                      );
                    })}
                  </div>
                );
              })
            )}
            {/* Empty catalog sections (only visible when not searching). */}
            {!query.trim() &&
              SECTION_ORDER.map((section) => {
                if (filteredEntries.some((e) => e.section === section))
                  return null;
                const emptyText = sectionEmptyText[section];
                if (!emptyText) return null;
                return (
                  <div
                    key={`empty-${section}`}
                    role="group"
                    aria-label={sectionTitles[section]}
                  >
                    <div
                      role="presentation"
                      className="bg-slate-50/50 px-3 py-1.5 text-2xs font-semibold uppercase tracking-label text-content-tertiary dark:bg-slate-800/50"
                    >
                      {sectionTitles[section]}
                    </div>
                    <div className="flex items-center justify-center gap-2 px-3 py-3 text-xs italic text-slate-400">
                      {(section === "plugins" && pluginsLoading) ||
                      (section === "agents" && definitionsLoading) ||
                      (section === "commands" && commandsLoading) ? (
                        <Loader2
                          size={14}
                          className="animate-spin motion-reduce:animate-none"
                        />
                      ) : null}
                      {emptyText}
                    </div>
                  </div>
                );
              })}
          </div>

          {/* Footer hints */}
          <div className="flex items-center gap-3 border-t border-slate-100 px-3 py-1.5 text-2xs text-slate-400 dark:border-slate-700/50">
            <span>
              <kbd className="rounded bg-slate-100 px-1 py-0.5 font-mono dark:bg-slate-700">
                &uarr;&darr;
              </kbd>{" "}
              {t("agent.slashCommand.hintNavigate", "navigate")}
            </span>
            <span>
              <kbd className="rounded bg-slate-100 px-1 py-0.5 font-mono dark:bg-slate-700">
                Enter
              </kbd>{" "}
              {t("agent.slashCommand.hintSelect", "select")}
            </span>
            <span>
              <kbd className="rounded bg-slate-100 px-1 py-0.5 font-mono dark:bg-slate-700">
                Esc
              </kbd>{" "}
              {t("agent.slashCommand.hintDismiss", "dismiss")}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
