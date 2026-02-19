/**
 * Error Boundary for Chat Components.
 *
 * Provides error recovery for chat message rendering with:
 * - Graceful error display
 * - Retry mechanism
 * - Error reporting
 * - Component isolation
 *
 * @example
 * <MessageErrorBoundary fallback={<ChatErrorFallback />}>
 *   <MessageStream>
 *     <AssistantMessage content="..." />
 *   </MessageStream>
 * </MessageErrorBoundary>
 */

import React, { Component, ErrorInfo, ReactNode } from 'react';

import { Button } from '@/components/ui';

/** Error boundary props */
export interface MessageErrorBoundaryProps {
  /** Child components */
  children: ReactNode;
  /** Custom fallback component */
  fallback?: ReactNode;
  /** Error callback */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
  /** Whether to show retry button */
  showRetry?: boolean;
  /** Custom error message */
  errorMessage?: string;
}

/** Error boundary state */
export interface MessageErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  retryCount: number;
}

/**
 * Default error fallback component.
 */
const DefaultErrorFallback: React.FC<{
  error: Error | null;
  onRetry: () => void;
  showRetry: boolean;
  retryCount: number;
}> = ({ error, onRetry, showRetry, retryCount }) => (
  <div
    className="p-4 my-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg"
    role="alert"
  >
    <div className="flex items-start gap-3">
      {/* Error icon */}
      <span className="material-symbols-outlined text-red-500 dark:text-red-400 text-xl">
        error
      </span>
      
      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-semibold text-red-800 dark:text-red-300">
          Failed to render message
        </h3>
        
        {error && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400 font-mono break-words">
            {error.message}
          </p>
        )}
        
        {retryCount > 0 && (
          <p className="mt-1 text-xs text-red-500 dark:text-red-400">
            Retry attempts: {retryCount}
          </p>
        )}
        
        {showRetry && (
          <Button
            onClick={onRetry}
            variant="outline"
            size="sm"
            className="mt-2 text-xs"
          >
            <span className="material-symbols-outlined text-sm mr-1">refresh</span>
            Try Again
          </Button>
        )}
      </div>
    </div>
  </div>
);

/**
 * Error boundary for chat message components.
 */
export class MessageErrorBoundary extends Component<
  MessageErrorBoundaryProps,
  MessageErrorBoundaryState
> {
  constructor(props: MessageErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: 0,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<MessageErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });
    
    // Log error to console in development
    if (process.env.NODE_ENV === 'development') {
      console.error('MessageErrorBoundary caught an error:', error, errorInfo);
    }
    
    // Call error callback
    this.props.onError?.(error, errorInfo);
    
    // Report to error tracking service (e.g., Sentry)
    if (typeof window !== 'undefined' && (window as any).Sentry) {
      (window as any).Sentry.captureException(error, { contexts: { react: errorInfo } });
    }
  }

  handleRetry = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: this.state.retryCount + 1,
    });
  };

  render(): ReactNode {
    const { hasError, error, retryCount } = this.state;
    const { fallback, showRetry = true, errorMessage } = this.props;

    if (hasError) {
      // Use custom fallback if provided
      if (fallback) {
        return fallback;
      }

      // Use default error fallback
      return (
        <DefaultErrorFallback
          error={error}
          onRetry={this.handleRetry}
          showRetry={showRetry}
          retryCount={retryCount}
        />
      );
    }

    return this.props.children;
  }
}

/**
 * Hook-based error boundary for functional components.
 * 
 * Note: This is a simplified version that only catches errors
 * in event handlers, not render errors. For full error boundary
 * functionality, use the class-based MessageErrorBoundary.
 */
export function useErrorHandler(
  onError?: (error: Error) => void
): {
  handleError: (error: Error) => void;
  hasError: boolean;
  error: Error | null;
  clearError: () => void;
} {
  const [hasError, setHasError] = React.useState(false);
  const [error, setError] = React.useState<Error | null>(null);

  const handleError = React.useCallback(
    (error: Error) => {
      setError(error);
      setHasError(true);
      onError?.(error);
    },
    [onError]
  );

  const clearError = React.useCallback(() => {
    setError(null);
    setHasError(false);
  }, []);

  return { handleError, hasError, error, clearError };
}

export default MessageErrorBoundary;
