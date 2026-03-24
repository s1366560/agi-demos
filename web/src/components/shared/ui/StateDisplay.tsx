/**
 * StateDisplay - Compound component for displaying UI states
 *
 * Provides consistent Loading, Empty, and Error states across the application.
 * Each sub-component can be used independently or together.
 *
 * @example
 * // Individual components
 * <StateDisplay.Loading message="Loading projects..." />
 * <StateDisplay.Empty icon={Folder} title="No projects" description="Create your first project" />
 * <StateDisplay.Error message="Failed to load" onRetry={handleRetry} />
 *
 * // Conditional rendering
 * {isLoading && <StateDisplay.Loading />}
 * {error && <StateDisplay.Error error={error} />}
 * {isEmpty && <StateDisplay.Empty title="No results" />}
 */

import { memo, type FC, type ReactNode } from 'react';

import { AlertCircle, Inbox, Loader2 } from 'lucide-react';

import type { LucideIcon } from 'lucide-react';

// ============================================================================
// LOADING STATE
// ============================================================================

export interface StateLoadingProps {
  /** Optional loading message */
  message?: string | undefined;
  /** Size variant */
  size?: 'sm' | 'md' | 'lg' | undefined;
  /** Use card wrapper */
  card?: boolean | undefined;
  /** Additional className */
  className?: string | undefined;
}

const LoadingComponent: FC<StateLoadingProps> = ({
  message,
  size = 'md',
  card = true,
  className = '',
}) => {
  const sizeMap = {
    sm: { spinner: 'h-5 w-5', text: 'text-xs', padding: 'p-4' },
    md: { spinner: 'h-8 w-8', text: 'text-sm', padding: 'p-8' },
    lg: { spinner: 'h-12 w-12', text: 'text-base', padding: 'p-12' },
  };

  const config = sizeMap[size];

  const content = (
    <div className={`flex flex-col items-center justify-center gap-3 ${config.padding}`}>
      <Loader2 className={`${config.spinner} animate-spin motion-reduce:animate-none text-primary`} />
      {message && <span className={`${config.text} text-slate-600 dark:text-slate-400`}>{message}</span>}
    </div>
  );

  if (card) {
    return (
      <div
        className={`
          bg-white dark:bg-slate-900 rounded-lg shadow-sm
          border border-slate-200 dark:border-slate-800
          ${className}
        `}
        data-testid="state-loading"
      >
        {content}
      </div>
    );
  }

  return (
    <div className={className} data-testid="state-loading">
      {content}
    </div>
  );
};

// ============================================================================
// EMPTY STATE
// ============================================================================

export interface StateEmptyProps {
  /** Icon to display (Lucide icon) */
  icon?: LucideIcon | undefined;
  /** Title text */
  title: string;
  /** Description text */
  description?: string | undefined;
  /** Action button */
  action?: ReactNode | undefined;
  /** Use card wrapper */
  card?: boolean | undefined;
  /** Additional className */
  className?: string | undefined;
}

const EmptyComponent: FC<StateEmptyProps> = ({
  icon: Icon = Inbox,
  title,
  description,
  action,
  card = true,
  className = '',
}) => {
  const content = (
    <div className="flex flex-col items-center justify-center text-center py-12 px-4">
      <div
        className="
          w-14 h-14 rounded-2xl
          bg-slate-100 dark:bg-slate-800
          flex items-center justify-center mb-4
        "
      >
        <Icon size={28} className="text-slate-300 dark:text-slate-600" />
      </div>
      <h3 className="text-base font-medium text-slate-700 dark:text-slate-300 mb-1">{title}</h3>
      {description && (
        <p className="text-sm text-slate-400 dark:text-slate-500 max-w-sm mb-4">{description}</p>
      )}
      {action}
    </div>
  );

  if (card) {
    return (
      <div
        className={`
          bg-white dark:bg-slate-900 rounded-lg shadow-sm
          border border-slate-200 dark:border-slate-800
          ${className}
        `}
        data-testid="state-empty"
      >
        {content}
      </div>
    );
  }

  return (
    <div className={className} data-testid="state-empty">
      {content}
    </div>
  );
};

// ============================================================================
// ERROR STATE
// ============================================================================

export interface StateErrorProps {
  /** Error message or Error object */
  error?: string | Error | undefined;
  /** Title for error */
  title?: string | undefined;
  /** Retry callback */
  onRetry?: (() => void) | undefined;
  /** Dismiss callback */
  onDismiss?: (() => void) | undefined;
  /** Use card wrapper */
  card?: boolean | undefined;
  /** Additional className */
  className?: string | undefined;
}

const ErrorComponent: FC<StateErrorProps> = ({
  error,
  title = 'Something went wrong',
  onRetry,
  onDismiss,
  card = true,
  className = '',
}) => {
  const message = typeof error === 'string' ? error : error?.message;

  const content = (
    <div className="flex flex-col items-center justify-center text-center py-12 px-4">
      <div
        className="
          w-14 h-14 rounded-2xl
          bg-red-100 dark:bg-red-900/30
          flex items-center justify-center mb-4
        "
      >
        <AlertCircle size={28} className="text-red-500 dark:text-red-400" />
      </div>
      <h3 className="text-base font-medium text-slate-700 dark:text-slate-300 mb-1">{title}</h3>
      {message && (
        <p className="text-sm text-slate-400 dark:text-slate-500 max-w-sm mb-4">{message}</p>
      )}
      <div className="flex items-center gap-2">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="
              inline-flex items-center gap-1.5 px-4 py-2
              bg-primary text-white text-sm font-medium
              rounded-lg hover:bg-primary/90 transition-colors
            "
          >
            Try Again
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="
              inline-flex items-center px-4 py-2
              bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400
              text-sm font-medium rounded-lg
              hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors
            "
          >
            Dismiss
          </button>
        )}
      </div>
    </div>
  );

  if (card) {
    return (
      <div
        className={`
          bg-white dark:bg-slate-900 rounded-lg shadow-sm
          border border-red-200 dark:border-red-900/50
          ${className}
        `}
        data-testid="state-error"
      >
        {content}
      </div>
    );
  }

  return (
    <div className={className} data-testid="state-error">
      {content}
    </div>
  );
};

// ============================================================================
// COMPOUND COMPONENT
// ============================================================================

export const StateDisplay = {
  Loading: memo(LoadingComponent),
  Empty: memo(EmptyComponent),
  Error: memo(ErrorComponent),
};

// Set display names
StateDisplay.Loading.displayName = 'StateDisplay.Loading';
StateDisplay.Empty.displayName = 'StateDisplay.Empty';
StateDisplay.Error.displayName = 'StateDisplay.Error';
