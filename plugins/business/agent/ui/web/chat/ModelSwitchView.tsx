import { useRef, useState, useCallback, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Bot, Check, ChevronDown, Loader2, Sparkles } from "lucide-react";
import type { TFunction } from "i18next";

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

export function ModelSwitchView({
  activeModelOverride,
  defaultModel,
  visibleModels,
  modelsLoading,
  disabled,
  onOpen,
  onSelect,
}: {
  activeModelOverride: string | null;
  defaultModel: string | null;
  visibleModels: string[];
  modelsLoading: boolean;
  disabled?: boolean | undefined;
  onOpen: () => void;
  onSelect: (value: string | null) => void;
}) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const select = (value: string | null) => {
    onSelect(value);
    setIsOpen(false);
  };
  const handleOpen = useCallback(() => {
    setIsOpen(true);
    onOpen();
  }, [onOpen]);

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

  const handleTriggerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (disabled) return;
      if (
        !isOpen &&
        (event.key === "ArrowDown" ||
          event.key === "Enter" ||
          event.key === " ")
      ) {
        event.preventDefault();
        handleOpen();
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setIsOpen(false);
      }
    },
    [disabled, isOpen, handleOpen],
  );

  const isOverrideActive = Boolean(activeModelOverride);
  const effectiveModel = activeModelOverride || defaultModel;
  const isAutoOverride = activeModelOverride?.toLowerCase() === "auto";

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        type="button"
        onClick={() => {
          if (disabled) return;
          if (isOpen) {
            setIsOpen(false);
            return;
          }
          handleOpen();
        }}
        disabled={disabled}
        onKeyDown={handleTriggerKeyDown}
        title={tFallback(t, "agent.modelSwitch.switchModel", "Switch Model")}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={`group flex h-8 items-center gap-1.5 px-2 text-sm rounded-lg transition-colors ${
          disabled
            ? "cursor-not-allowed text-content-tertiary opacity-40"
            : `text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900 ${
                isOpen ? "text-primary bg-primary/5" : ""
              } ${isOverrideActive && !isOpen ? "text-primary" : ""}`
        }`}
      >
        <Bot size={16} className="shrink-0" />
        <span className="hidden max-w-[152px] truncate min-w-0 text-xs font-medium lg:inline">
          {isAutoOverride
            ? tFallback(t, "agent.modelSwitch.autoRouter", "Auto (Router)")
            : (effectiveModel ??
              tFallback(t, "agent.modelSwitch.title", "Model"))}
        </span>
        <ChevronDown
          size={12}
          className={`shrink-0 text-slate-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
        />
      </button>

      {isOpen && (
        <div className="absolute bottom-full left-0 mb-2 z-50 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 shadow-lg shadow-slate-200/40 dark:shadow-slate-950/20">
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100 dark:border-slate-700/50">
            <span className="text-xs text-slate-400">
              {tFallback(t, "agent.modelSwitch.title", "Model")}
            </span>
            {isOverrideActive && (
              <button
                type="button"
                onClick={() => {
                  select(null);
                }}
                className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
              >
                {tFallback(t, "agent.modelSwitch.reset", "Reset")}
              </button>
            )}
          </div>
          <div
            className="max-h-64 overflow-y-auto py-1"
            role="listbox"
            aria-label={tFallback(
              t,
              "agent.modelSwitch.switchModel",
              "Switch Model",
            )}
          >
            {modelsLoading ? (
              <div className="flex items-center justify-center gap-2 px-3 py-4 text-sm text-slate-400">
                <Loader2
                  size={14}
                  className="animate-spin motion-reduce:animate-none"
                  aria-hidden
                />
                {tFallback(
                  t,
                  "agent.modelSwitch.loadingModels",
                  "Loading models…",
                )}
              </div>
            ) : visibleModels.length === 0 && !defaultModel ? (
              <div className="px-3 py-4 text-center text-sm text-slate-400">
                {tFallback(
                  t,
                  "agent.modelSwitch.noModels",
                  "No models available",
                )}
              </div>
            ) : (
              <>
                {/* Default (project/provider) option */}
                <button
                  type="button"
                  role="option"
                  aria-selected={!isOverrideActive}
                  onClick={() => {
                    select(null);
                  }}
                  className={`w-full text-left px-3 py-2 flex items-center justify-between gap-2 rounded-md text-sm transition-colors duration-150 cursor-pointer ${
                    !isOverrideActive
                      ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                      : "text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                  }`}
                >
                  <div className="flex flex-col min-w-0">
                    <span className="font-medium truncate">
                      {tFallback(
                        t,
                        "agent.modelSwitch.defaultOption",
                        "Default",
                      )}
                    </span>
                    {defaultModel && (
                      <span className="text-xs text-slate-400 dark:text-slate-500 truncate">
                        {defaultModel}
                      </span>
                    )}
                  </div>
                  {!isOverrideActive && (
                    <Check
                      size={16}
                      className="text-blue-600 dark:text-blue-400 shrink-0"
                    />
                  )}
                </button>

                {/* Auto router option */}
                <button
                  type="button"
                  role="option"
                  aria-selected={isAutoOverride}
                  onClick={() => {
                    select("auto");
                  }}
                  className={`w-full text-left px-3 py-2 flex items-center justify-between gap-2 rounded-md text-sm transition-colors duration-150 cursor-pointer ${
                    isAutoOverride
                      ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                      : "text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Sparkles size={16} className="shrink-0 text-slate-400" />
                    <div className="flex flex-col min-w-0">
                      <span className="font-medium truncate">
                        {tFallback(
                          t,
                          "agent.modelSwitch.autoRouter",
                          "Auto (Router)",
                        )}
                      </span>
                      <span className="text-xs text-slate-400 dark:text-slate-500 truncate">
                        {tFallback(
                          t,
                          "agent.modelSwitch.autoRouterDescription",
                          "Let the platform pick the best model per turn",
                        )}
                      </span>
                    </div>
                  </div>
                  {isAutoOverride && (
                    <Check
                      size={16}
                      className="text-blue-600 dark:text-blue-400 shrink-0"
                    />
                  )}
                </button>

                {visibleModels.map((name) => {
                  const isSelected = activeModelOverride === name;
                  return (
                    <button
                      key={name}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      onClick={() => {
                        select(name);
                      }}
                      className={`w-full text-left px-3 py-2 flex items-center justify-between gap-2 rounded-md text-sm transition-colors duration-150 cursor-pointer ${
                        isSelected
                          ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                          : "text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
                      }`}
                    >
                      <span className="truncate font-medium">{name}</span>
                      {isSelected && (
                        <Check
                          size={16}
                          className="text-blue-600 dark:text-blue-400 shrink-0"
                        />
                      )}
                    </button>
                  );
                })}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
