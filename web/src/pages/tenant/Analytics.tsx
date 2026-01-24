import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    ArcElement,
} from 'chart.js'
import { Line, Pie } from 'react-chartjs-2'
import { useTenantStore } from '../../stores/tenant'
import { projectAPI } from '../../services/api'
import { Project } from '../../types/memory'

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    ArcElement
)

export const Analytics: React.FC = () => {
    const { t } = useTranslation()
    const { currentTenant } = useTenantStore()
    const [projects, setProjects] = useState<Project[]>([])
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        const fetchProjects = async () => {
            if (currentTenant) {
                try {
                    const data = await projectAPI.list(currentTenant.id)
                    setProjects(data)
                } catch (error) {
                    console.error('Failed to fetch projects:', error)
                } finally {
                    setLoading(false)
                }
            }
        }
        fetchProjects()
    }, [currentTenant])

    if (!currentTenant) return <div className="p-8 text-center text-slate-500">{t('tenant.analytics.no_workspace')}</div>
    if (loading) return <div className="p-8 text-center text-slate-500"><span className="material-symbols-outlined animate-spin mr-2">progress_activity</span>{t('tenant.analytics.loading')}</div>

    // Mock data for charts
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

    const lineOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: false,
            },
            title: {
                display: false,
            },
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: {
                    color: 'rgba(0, 0, 0, 0.05)',
                },
            },
            x: {
                grid: {
                    display: false,
                },
            },
        },
    }

    const pieOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                position: 'right' as const,
            },
        },
    }

    return (
        <div className="max-w-7xl mx-auto p-6 md:p-8 flex flex-col gap-8">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 dark:text-white">{t('tenant.analytics.title')}</h1>
                    <p className="text-slate-500 dark:text-slate-400 mt-1">{t('tenant.analytics.workspace_info')}</p>
                </div>
                <div className="flex items-center gap-3 bg-white dark:bg-surface-dark px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm">
                    <div className="flex flex-col items-end">
                        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{t('tenant.analytics.storage_usage')}</span>
                        <span className="text-sm font-bold text-slate-900 dark:text-white">45.2 GB <span className="text-slate-400 font-normal">/ 100 GB</span></span>
                    </div>
                    <div className="h-8 w-8 rounded-full bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center text-purple-600 dark:text-purple-400">
                        <span className="material-symbols-outlined text-[20px]">database</span>
                    </div>
                </div>
            </div>

            {/* KPI Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                    <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{t('tenant.analytics.total_memories')}</p>
                    <h3 className="text-3xl font-bold text-slate-900 dark:text-white mt-2">12,450</h3>
                    <div className="flex items-center gap-1 mt-2 text-sm text-green-600 font-medium">
                        <span className="material-symbols-outlined text-[16px]">trending_up</span>
                        <span>+12% {t('tenant.analytics.growing')}</span>
                    </div>
                </div>
                <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                    <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{t('tenant.analytics.active_projects')}</p>
                    <h3 className="text-3xl font-bold text-slate-900 dark:text-white mt-2">{projects.length}</h3>
                    <div className="flex items-center gap-1 mt-2 text-sm text-slate-500">
                        <span>{t('tenant.analytics.project_count')}</span>
                    </div>
                </div>
                <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                    <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{t('tenant.analytics.avg_per_project')}</p>
                    <h3 className="text-3xl font-bold text-slate-900 dark:text-white mt-2">4,150</h3>
                    <div className="flex items-center gap-1 mt-2 text-sm text-slate-500">
                        <span>{t('tenant.analytics.avg_memories')}</span>
                    </div>
                </div>
                <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                    <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{t('tenant.analytics.plan')}</p>
                    <h3 className="text-3xl font-bold text-slate-900 dark:text-white mt-2 capitalize">{currentTenant.plan}</h3>
                    <div className="flex items-center gap-1 mt-2 text-sm text-purple-600 font-medium">
                        <span>{t('tenant.analytics.quota')}</span>
                    </div>
                </div>
            </div>

            {/* Charts Section */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                {/* Memory Growth Chart */}
                <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                    <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-6">{t('tenant.analytics.creation_trend')}</h3>
                    <div className="h-80 w-full relative">
                        <Line options={lineOptions} data={memoryGrowthData} />
                    </div>
                </div>

                {/* Storage Distribution */}
                <div className="bg-white dark:bg-surface-dark p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                    <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-6">{t('tenant.analytics.storage_distribution')}</h3>
                    <div className="h-80 w-full relative flex items-center justify-center">
                        {projects.length > 0 ? (
                            <Pie options={pieOptions} data={projectStorageData} />
                        ) : (
                            <div className="text-slate-400">{t('tenant.analytics.no_data')}</div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
