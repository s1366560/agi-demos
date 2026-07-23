import { Component, ErrorInfo, ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Result, Button, theme } from 'antd';

/**
 * Props for ErrorBoundary component
 */
interface Props {
  /** Child components to be wrapped by the error boundary */
  children: ReactNode;
  /**
   * Custom fallback UI to render when an error is caught.
   * Accepts a static node or a render function receiving the caught
   * error and a reset callback (for retry / recovery actions).
   */
  fallback?: ReactNode | ((error: Error | undefined, onReset: () => void) => ReactNode) | undefined;
  /** Optional context identifier for error source (e.g., "Agent", "Project", "Tenant") */
  context?: string | undefined;
  /** Optional custom error handler callback */
  onError?: ((error: Error, errorInfo: ErrorInfo) => void) | undefined;
  /** Whether to show the home button in the fallback UI */
  showHomeButton?: boolean | undefined;
}

/**
 * Internal state for ErrorBoundary
 */
interface State {
  /** Whether an error has been caught */
  hasError: boolean;
  /** The error that was caught, if any */
  error?: Error | undefined;
}

/**
 * ErrorBoundary Component - React error boundary for catching errors
 *
 * Catches JavaScript errors anywhere in the child component tree,
 * logs those errors, and displays a fallback UI. Prevents the entire
 * app from crashing due to errors in individual components.
 *
 * @component
 *
 * @features
 * - Catches errors in child component tree
 * - Logs errors to console (ready for Sentry integration)
 * - Displays user-friendly error UI with retry option
 * - Shows error stack trace in development mode
 * - Supports custom fallback UI
 * - Internationalization support via react-i18next
 * - Optional context prefix for error identification
 * - Custom error handler callback support
 * - Configurable home button visibility
 *
 * @example
 * ```tsx
 * import { ErrorBoundary } from '@/components/common/ErrorBoundary'
 *
 * function App() {
 *   return (
 *     <ErrorBoundary>
 *       <YourComponent />
 *     </ErrorBoundary>
 *   )
 * }
 * ```
 *
 * @example
 * ```tsx
 * // With context and custom error handler
 * <ErrorBoundary
 *   context="Agent"
 *   onError={(error, errorInfo) => {
 *     console.error('[Agent] Error:', error)
 *   }}
 *   showHomeButton={true}
 * >
 *   <YourComponent />
 * </ErrorBoundary>
 * ```
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  /**
   * Log error with optional context prefix
   */
  private logError(error: Error, errorInfo: ErrorInfo): void {
    const prefix = this.props.context ? `[${this.props.context}]` : 'ErrorBoundary';
    console.error(`${prefix} caught an error:`, error, errorInfo);
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error to console with context prefix
    this.logError(error, errorInfo);

    // Call custom error handler if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }

    // Log error to error reporting service (e.g., Sentry)
    // logErrorToService(error, errorInfo)
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: undefined });
  };

  override render(): ReactNode {
    const { hasError, error } = this.state;
    const { children, fallback, showHomeButton = true } = this.props;

    if (hasError) {
      // Custom fallback UI (static node or render function)
      if (fallback) {
        return typeof fallback === 'function' ? fallback(error, this.handleReset) : fallback;
      }

      // Default error UI
      return (
        <ErrorFallback error={error} onReset={this.handleReset} showHomeButton={showHomeButton} />
      );
    }

    return children;
  }
}

/**
 * Props for ErrorFallback component
 */
interface ErrorFallbackProps {
  /** The error that occurred */
  error?: Error | undefined;
  /** Callback to reset the error boundary and retry */
  onReset: () => void;
  /** Whether to show the home button */
  showHomeButton?: boolean | undefined;
  /**
   * Extra buttons injected between the retry and home buttons
   * (e.g. context-aware navigation actions from RouteErrorBoundary).
   */
  extra?: ReactNode;
}

/**
 * Default error fallback UI component
 *
 * Displays a user-friendly error message with retry and home buttons.
 * Shows error stack trace in development mode for debugging.
 * This is the single shared fallback implementation; RouteErrorBoundary
 * only injects its navigation button group via the `extra` prop.
 */
export function ErrorFallback({
  error,
  onReset,
  showHomeButton = true,
  extra,
}: ErrorFallbackProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const handleGoHome = () => {
    onReset();
    void navigate('/');
  };

  const buttons: ReactNode[] = [
    <Button type="primary" key="retry" onClick={onReset}>
      {t('error.retry', { defaultValue: 'Try Again' })}
    </Button>,
  ];

  if (extra) {
    buttons.push(extra);
  }

  if (showHomeButton) {
    buttons.push(
      <Button key="home" onClick={handleGoHome}>
        {t('error.home', { defaultValue: 'Go Home' })}
      </Button>
    );
  }

  return (
    <div style={{ padding: '50px', textAlign: 'center' }}>
      <Result
        status="error"
        title={t('error.title', { defaultValue: 'Something went wrong' })}
        subTitle={
          error?.message ||
          t('error.subtitle', {
            defaultValue: 'An unexpected error occurred. Please try again.',
          })
        }
        extra={buttons}
      />
      {error && process.env.NODE_ENV === 'development' && (
        <details style={{ marginTop: '20px', textAlign: 'left' }}>
          <summary style={{ cursor: 'pointer', marginBottom: '10px' }}>
            {t('error.details', { defaultValue: 'Error Details' })}
          </summary>
          <pre
            style={{
              background: token.colorFillSecondary,
              color: token.colorText,
              padding: '10px',
              borderRadius: '4px',
              overflow: 'auto',
              maxHeight: '300px',
            }}
          >
            {error.stack}
          </pre>
        </details>
      )}
    </div>
  );
}

export default ErrorBoundary;
