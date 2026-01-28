import { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Result, Button } from 'antd'
import { useTranslation } from 'react-i18next'
import { ErrorBoundary } from './ErrorBoundary'
import type { ErrorInfo } from 'react'

/**
 * Props for RouteErrorBoundary component
 */
export interface RouteErrorBoundaryProps {
    /** Child components to be wrapped by the error boundary */
    children: ReactNode
    /** Route context name (required) - identifies the source of the error */
    context: string
    /** Optional fallback path for navigation recovery */
    fallbackPath?: string
}

/**
 * Error fallback UI component with context-aware navigation
 *
 * Displays a user-friendly error message with navigation to fallback path.
 * Shows error context and stack trace in development mode for debugging.
 */
function RouteErrorFallback({
    error,
    context,
    fallbackPath,
    onReset,
}: {
    error?: Error
    context: string
    fallbackPath?: string
    onReset: () => void
}) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const handleGoBack = () => {
        if (fallbackPath) {
            navigate(fallbackPath)
        } else {
            navigate(-1)
        }
    }

    const buttons = [
        <Button key="retry" onClick={onReset}>
            {t('error.retry', { defaultValue: 'Try Again' })}
        </Button>,
        <Button type="primary" key="back" onClick={handleGoBack}>
            {fallbackPath
                ? t('error.goToPage', { defaultValue: `Go to ${fallbackPath}` })
                : t('error.goBack', { defaultValue: 'Go Back' })}
        </Button>,
        <Button key="home" onClick={() => navigate('/')}>
            {t('error.home', { defaultValue: 'Go Home' })}
        </Button>,
    ]

    return (
        <div style={{ padding: '50px', textAlign: 'center' }}>
            <Result
                status="error"
                title={t('error.title', { defaultValue: 'Something went wrong' })}
                subTitle={
                    error?.message ||
                    t('error.subtitle', {
                        defaultValue: `An unexpected error occurred in ${context}. Please try again.`,
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
                            background: '#f5f5f5',
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
    )
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
 * export const ProjectLayout: React.FC = () => {
 *   const { projectId } = useParams()
 *   return (
 *     <RouteErrorBoundary context="Project" fallbackPath={`/project/${projectId}`}>
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
            fallback={<RouteErrorFallback error={undefined} context={context} fallbackPath={fallbackPath} onReset={() => {}} />}
            onError={(error: Error, errorInfo: ErrorInfo) => {
                console.error(`[${context}] Route error:`, error)
                console.error('Component stack:', errorInfo.componentStack)
            }}
        >
            {children}
        </ErrorBoundary>
    )
}

export default RouteErrorBoundary
