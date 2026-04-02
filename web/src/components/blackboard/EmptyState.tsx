import type { ReactNode } from 'react';

export interface EmptyStateProps {
  children: ReactNode;
}

export function EmptyState({ children }: EmptyStateProps) {
  return (
    <div className="rounded-xl border border-dashed border-border-separator bg-surface-light p-5 text-center text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
      {children}
    </div>
  );
}
