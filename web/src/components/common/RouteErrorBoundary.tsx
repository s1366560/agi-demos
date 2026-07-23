import { ReactNode } from 'react';
import type { ErrorInfo } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Button } from 'antd';

import { ErrorBoundary, ErrorFallback } from './ErrorBoundary';

/**
 * Props for RouteErrorBoundary component
 */
export interface RouteErrorBoundaryProps {
  /** Child components to be wrapped by the error boundary */
  children: ReactNode;
  /** Route context name (required) - identifies the source of the error */
  context: string;
  /** Optional fallback path for navigation recovery */
  fallbackPath?: string | undefined;
}

/**
 * Context-aware navigation button group injected into the shared
 * ErrorFallback as its `extra` actions.
 */
function RouteNavigationButtons({ fallbackPath }: { fallbackPath?: string | undefined }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const handleGoBack = () => {
    if (fallbackPath) {
      void navigate(fallbackPath);
    } else {
      void navigate(-1);
    }
  };

  return (
    <Button key="back" onClick={handleGoBack}>
      {fallbackPath
        ? t('error.goToPage', { defaultValue: 'Go to page' })
        : t('error.goBack', { defaultValue: 'Go Back' })}
    </Button>
  );
}

/**
 * RouteErrorBoundary Component - Error boundary with context-aware fallback
 *
 * Wraps the existing ErrorBoundary to provide route-specific error handling
 * with configurable fallback paths. This is designed for use in Layout components
 * to catch errors in nested routes and provide appropriate navigation options.
 *
 * @component
 *
 * @features
 * - Catches errors in child component tree
 * - Context-aware error messages
 * - Configurable fallback navigation path
 * - Shows error stack trace in development mode
 * - Internationalization support via react-i18next
 *
 * @example
 * ```tsx
 * import { RouteErrorBoundary } from '@/components/common/RouteErrorBoundary'
 *
 * export const TenantProjectRoute: React.FC = () => {
 *   const { projectId } = useParams()
 *   return (
 *     <RouteErrorBoundary context="Project" fallbackPath={`/tenant/${tenantId}/project/${projectId}`}>
 *       <Outlet />
 *     </RouteErrorBoundary>
 *   )
 * }
 * ```
 */
export function RouteErrorBoundary({
  children,
  context,
  fallbackPath = '/',
}: RouteErrorBoundaryProps) {
  return (
    <ErrorBoundary
      context={context}
      fallback={(error, onReset) => (
        <ErrorFallback
          error={error}
          onReset={onReset}
          extra={<RouteNavigationButtons fallbackPath={fallbackPath} />}
        />
      )}
      onError={(error: Error, errorInfo: ErrorInfo) => {
        console.error(`[${context}] Route error:`, error);
        console.error('Component stack:', errorInfo.componentStack);
      }}
    >
      {children}
    </ErrorBoundary>
  );
}

export default RouteErrorBoundary;
