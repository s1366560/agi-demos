import type { ComponentPropsWithRef } from 'react';

export function ChatDraftInput(props: ComponentPropsWithRef<'textarea'>) {
  return (
    <textarea
      id="agent-message-input"
      {...props}
      rows={1}
      data-testid="chat-input"
      dir="auto"
      autoCapitalize="sentences"
      className="
                  h-auto min-w-40 flex-1 bg-transparent px-1 py-1
                  text-sm leading-relaxed text-slate-800 dark:text-slate-100
                  placeholder:text-content-tertiary
                  focus:outline-none
                  overflow-y-auto overflow-x-hidden
                  break-words font-sans
                  scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-slate-600
                  scrollbar-track-transparent scrollbar-w-1.5
                  hover:scrollbar-thumb-slate-400 dark:hover:scrollbar-thumb-slate-500
                "
      style={{
        resize: 'none',
        minHeight: '32px',
        maxHeight: '100%',
      }}
    />
  );
}
