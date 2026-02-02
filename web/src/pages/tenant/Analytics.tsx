import React, { useEffect, useState, lazy, Suspense, memo, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useTenantStore } from '../../stores/tenant'
import { projectAPI } from '../../services/api'
import { Project } from '../../types/memory'

// Dynamic imports for chart libraries to reduce initial bundle size
const ChartComponents = lazy(() => import('./ChartComponents'))

// KPI Card component with memo for performance optimization
interface KPICardProps {
    label: string
    value: string | number
    subtext?: string
    subtextIcon?: string
    subtextColorClass?: string
}

const KPICard = memo<KPICardProps>(({ label, value, subtext, subtextIcon, subtextColorClass }) => {
    return (
        <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</p>
            <h3 className="text-3xl font-bold text-slate-900 dark:text-white mt-2">{value}</h3>
            {subtext && (
                <div className={`flex items-center gap-1 mt-2 text-sm font-medium ${subtextColorClass || 'text-slate-500'}`}>
                    {subtextIcon && <span className="material-symbols-outlined text-[16px]">{subtextIcon}</span>}
                    <span>{subtext}</span>
                </div>
            )}
        </div>
    );
});
KPICard.displayName = 'KPICard';

// Loading state component
const LoadingState = memo<{ message: string }>(({ message }) => (
    <div className="p-8 text-center text-slate-500">
        <span className="material-symbols-outlined animate-spin mr-2">progress_activity</span>
        {message}
    </div>
));
LoadingState.displayName = 'LoadingState';

// Analytics header component
interface AnalyticsHeaderProps {
    title: string
    subtitle: string
    storageLabel: string
    storageValue: string
}

const AnalyticsHeader = memo<AnalyticsHeaderProps>(({ title, subtitle, storageLabel, storageValue }) => (
    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">{title}</h1>
            <p className="text-slate-500 dark:text-slate-400 mt-1">{subtitle}</p>
        </div>
        <div className="flex items-center gap-3 bg-white dark:bg-surface-dark px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm">
            <div className="flex flex-col items-end">
                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{storageLabel}</span>
                <span className="text-sm font-bold text-slate-900 dark:text-white">{storageValue}</span>
            </div>
            <div className="h-8 w-8 rounded-full bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center text-purple-600 dark:text-purple-400">
                <span className="material-symbols-outlined text-[20px]">database</span>
            </div>
        </div>
    </div>
));
AnalyticsHeader.displayName = 'AnalyticsHeader';

export const Analytics: React.FC = memo(() => {
    const { t } = useTranslation()
    const { currentTenant } = useTenantStore()
    const [projects, setProjects] = useState<Project[]>([])
    const [loading, setLoading] = useState(true)

    const fetchProjects = useCallback(async () => {
        if (currentTenant) {
            try {
                const data = await projectAPI.list(currentTenant.id)
                setProjects(data.projects)
            } catch (error) {
                console.error('Failed to fetch projects:', error)
            } finally {
                setLoading(false)
            }
        }
    }, [currentTenant])

    useEffect(() => {
        fetchProjects()
    }, [fetchProjects])

    if (!currentTenant) return <div className="p-8 text-center text-slate-500">{t('tenant.analytics.no_workspace')}</div>
    if (loading) return <LoadingState message={t('tenant.analytics.loading')} />

    // Memoize chart data to prevent recalculation on re-renders
    const chartData = useMemo(() => {
        const memoryGrowthLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul']
        const memoryGrowthData = {
            labels: memoryGrowthLabels,
            datasets: [
                {
                    label: 'Memories',
                    data: [40, 300, 200, 278, 189, 239, 349],
                    borderColor: 'rgb(99, 102, 241)',
                    backgroundColor: 'rgba(99, 102, 241, 0.5)',
                    tension: 0.3,
                },
            ],
        }

        const projectStorageData = {
            labels: projects.map(p => p.name),
            datasets: [
                {
                    data: projects.map(() => Math.floor(Math.random() * 100)),
                    backgroundColor: [
                        'rgba(99, 102, 241, 0.8)',
                        'rgba(139, 92, 246, 0.8)',
                        'rgba(236, 72, 153, 0.8)',
                        'rgba(16, 185, 129, 0.8)',
                        'rgba(245, 158, 11, 0.8)',
                    ],
                    borderWidth: 0,
                },
            ],
        }

        return { memoryGrowthData, projectStorageData }
    }, [projects])

    // Memoize chart options
    const lineOptions = useMemo(() => ({
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            title: { display: false },
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: { color: 'rgba(0, 0, 0, 0.05)' },
            },
            x: {
                grid: { display: false },
            },
        },
    }), [])

    const pieOptions = useMemo(() => ({
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: 'right' as const },
        },
    }), [])

    return (
        <div className="max-w-full mx-auto flex flex-col gap-8">
            {/* Header */}
            <AnalyticsHeader
                title={t('tenant.analytics.title')}
                subtitle={t('tenant.analytics.workspace_info')}
                storageLabel={t('tenant.analytics.storage_usage')}
                storageValue="45.2 GB / 100 GB"
            />

            {/* KPI Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <KPICard
                    label={t('tenant.analytics.total_memories')}
                    value="12,450"
                    subtext="+12% Growing"
                    subtextIcon="trending_up"
                    subtextColorClass="text-green-600"
                />
                <KPICard
                    label={t('tenant.analytics.active_projects')}
                    value={projects.length}
                    subtext={t('tenant.analytics.project_count')}
                />
                <KPICard
                    label={t('tenant.analytics.avg_per_project')}
                    value="4,150"
                    subtext={t('tenant.analytics.avg_memories')}
                />
                <KPICard
                    label={t('tenant.analytics.plan')}
                    value={currentTenant.plan}
                    subtext={t('tenant.analytics.quota')}
                    subtextColorClass="text-purple-600"
                />
            </div>

            {/* Charts Section */}
            <Suspense fallback={
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                    <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm flex items-center justify-center h-96">
                        <span className="text-slate-400">{t('common.loading')}</span>
                    </div>
                    <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm flex items-center justify-center h-96">
                        <span className="text-slate-400">{t('common.loading')}</span>
                    </div>
                </div>
            }>
                <ChartComponents
                    memoryGrowthData={chartData.memoryGrowthData}
                    projectStorageData={chartData.projectStorageData}
                    lineOptions={lineOptions}
                    pieOptions={pieOptions}
                    projectsLength={projects.length}
                    t={t}
                />
            </Suspense>
        </div>
    );
});
Analytics.displayName = 'Analytics';
