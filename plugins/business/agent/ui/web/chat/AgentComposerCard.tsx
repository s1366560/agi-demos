import type { ComponentPropsWithoutRef, ReactNode } from 'react';

interface ComposerCardProps extends ComponentPropsWithoutRef<'section'> {
  isFocused: boolean;
  isDragging?: boolean | undefined;
  isPlanMode?: boolean | undefined;
  disabled?: boolean | undefined;
}

export function AgentComposerCard({
  isFocused,
  isDragging,
  isPlanMode,
  disabled,
  ...props
}: ComposerCardProps) {
  return (
    <section
      data-tour="input-bar"
      {...props}
      className={`
            flex-1 flex flex-col min-h-0 min-w-0 rounded-md border relative
            bg-white dark:bg-slate-800
            transition-[border-color,box-shadow] duration-200 ease-out
            ${
              isDragging
                ? 'border-primary/55 ring-2 ring-primary/15 shadow-[0_1px_5px_rgba(0,112,243,0.08)]'
                : isPlanMode
                  ? 'border-primary/40 ring-2 ring-primary/10 shadow-[0_1px_4px_rgba(0,112,243,0.06)]'
                  : isFocused
                    ? 'border-primary/25 shadow-[0_1px_4px_rgba(0,112,243,0.045)] ring-2 ring-primary/5'
                    : 'border-slate-200/45 dark:border-slate-700/45 shadow-[0_1px_3px_rgba(15,23,42,0.035)] dark:shadow-[0_1px_3px_rgba(0,0,0,0.12)]'
            }
            ${disabled ? 'opacity-60 pointer-events-none' : ''}
          `}
    />
  );
}

export function AgentDraftSurface({
  controls,
  children,
}: {
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      data-testid="chat-input-body"
      className="relative flex min-h-0 min-w-0 flex-1 px-3 py-2 sm:px-4 overflow-visible"
    >
      {controls}
      <div
        data-testid="chat-input-surface"
        className="flex h-full min-h-11 w-full min-w-0 flex-wrap content-start items-start gap-1.5 px-2 py-1.5"
      >
        {children}
      </div>
    </div>
  );
}
