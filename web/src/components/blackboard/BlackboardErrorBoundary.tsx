import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface BlackboardErrorBoundaryProps {
  children: ReactNode;
  fallbackLabel?: string;
  retryLabel?: string;
}

interface BlackboardErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class BlackboardErrorBoundary extends Component<
  BlackboardErrorBoundaryProps,
  BlackboardErrorBoundaryState
> {
  constructor(props: BlackboardErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): BlackboardErrorBoundaryState {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[BlackboardErrorBoundary]', error, info.componentStack);
  }

  private readonly handleRetry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  override render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="flex flex-col items-center justify-center gap-4 rounded-lg border border-error/25 bg-error/10 p-8 text-center"
        >
          <div className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {this.props.fallbackLabel ?? 'Something went wrong'}
          </div>
          <p className="max-w-lg break-words text-sm leading-6 text-text-secondary dark:text-text-muted">
            {this.state.error?.message ?? 'An unexpected error occurred.'}
          </p>
          <button
            type="button"
            onClick={this.handleRetry}
            className="min-h-10 rounded-lg border border-error/25 bg-surface-light px-5 text-sm font-medium text-status-text-error transition-colors motion-reduce:transition-none hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:bg-white/5 dark:text-status-text-error-dark"
          >
            {this.props.retryLabel ?? 'Try again'}
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
