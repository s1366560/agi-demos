import { Component, ErrorInfo, ReactNode } from 'react'
import { Result, Button } from 'antd'
import { useTranslation } from 'react-i18next'

interface Props {
    children: ReactNode
    fallback?: ReactNode
}

interface State {
    hasError: boolean
    error?: Error
}

/**
 * Error Boundary Component
 * Catches JavaScript errors anywhere in the child component tree,
 * logs those errors, and displays a fallback UI.
 *
 * Usage:
 * ```tsx
 * <ErrorBoundary>
 *   <YourComponent />
 * </ErrorBoundary>
 * ```
 */
export class ErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props)
        this.state = { hasError: false }
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error }
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
        // Log error to console
        console.error('ErrorBoundary caught an error:', error, errorInfo)

        // Log error to error reporting service (e.g., Sentry)
        // logErrorToService(error, errorInfo)
    }

    handleReset = (): void => {
        this.setState({ hasError: false, error: undefined })
    }

    render(): ReactNode {
        const { hasError, error } = this.state
        const { children, fallback } = this.props

        if (hasError) {
            // Custom fallback UI
            if (fallback) {
                return fallback
            }

            // Default error UI
            return <ErrorFallback error={error} onReset={this.handleReset} />
        }

        return children
    }
}

/**
 * Default error fallback UI component
 */
function ErrorFallback({ error, onReset }: { error?: Error; onReset: () => void }) {
    const { t } = useTranslation()

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
                extra={[
                    <Button type="primary" key="retry" onClick={onReset}>
                        {t('error.retry', { defaultValue: 'Try Again' })}
                    </Button>,
                    <Button key="home" onClick={() => (window.location.href = '/')}>
                        {t('error.home', { defaultValue: 'Go Home' })}
                    </Button>,
                ]}
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

export default ErrorBoundary
