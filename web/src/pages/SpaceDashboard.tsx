import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
    LayoutDashboard,
    Folder,
    Users,
    Settings,
    Plus,
    ArrowLeft,
    CreditCard,
    BarChart2,
    Database,
    FolderOpen,
    Cpu,
    Cloud,
    Beaker,
    MoreVertical,
    Badge,
    Globe
} from 'lucide-react';
import { AppLayout, NavigationGroup } from '@/components/shared/layouts/AppLayout';
import { useTenantStore } from '../stores/tenant';
import { useProjectStore } from '../stores/project';
import { ProjectCreateModal } from '@/components/tenant/ProjectCreateModal';
import { Project } from '../types/memory';
import { tenantAPI } from '../services/api';

export const SpaceDashboard: React.FC = () => {
    const { t } = useTranslation();
    const { spaceId } = useParams<{ spaceId: string }>();
    const navigate = useNavigate();
    const { currentTenant, getTenant } = useTenantStore();
    const { projects, listProjects, setCurrentProject } = useProjectStore();
    const [isCreateProjectOpen, setIsCreateProjectOpen] = useState(false);
    const [activeTab, setActiveTab] = useState('overview');
    const [stats, setStats] = useState<any>(null);

    useEffect(() => {
        if (spaceId) {
            getTenant(spaceId);
            listProjects(spaceId);

            const fetchStats = async () => {
                try {
                    const data = await tenantAPI.getStats(spaceId);
                    setStats(data);
                } catch (error) {
                    console.error("Failed to fetch tenant stats", error);
                }
            };
            fetchStats();
        }
    }, [spaceId, getTenant, listProjects]);

    const handleEnterProject = (project: Project) => {
        setCurrentProject(project);
        navigate(`/space/${spaceId}/project/${project.id}`);
    };

    const navGroups: NavigationGroup[] = [
        {
            title: t('nav.platform').toUpperCase(),
            items: [
                { id: 'overview', label: t('nav.overview'), icon: LayoutDashboard, onClick: () => setActiveTab('overview') },
                { id: 'projects', label: t('nav.projects'), icon: Folder, onClick: () => setActiveTab('projects') },
                { id: 'users', label: t('nav.users'), icon: Users, onClick: () => setActiveTab('users') },
                { id: 'analytics', label: t('nav.analytics'), icon: BarChart2, onClick: () => setActiveTab('analytics') },
            ]
        },
        {
            title: t('nav.administration').toUpperCase(),
            items: [
                { id: 'billing', label: t('nav.billing'), icon: CreditCard, onClick: () => setActiveTab('billing') },
                { id: 'settings', label: t('nav.settings'), icon: Settings, onClick: () => setActiveTab('settings') },
            ]
        }
    ];

    const BackButton = (
        <button
            onClick={() => navigate('/spaces')}
            className="p-1 hover:bg-blue-700 rounded transition-colors mr-2"
            title={t('space.dashboard.back_button_title') || "Back to Spaces"}
        >
            <ArrowLeft className="h-5 w-5 text-white" />
        </button>
    );

    const generatePath = (data: { usage: number }[], width: number, height: number) => {
        if (!data || data.length === 0) return '';
        const points = data.map((point, i) => {
            const x = (i / (data.length - 1)) * width;
            const y = height - (point.usage / 100) * height;
            return `${x},${y}`;
        });
        return `M 0,${height} L 0,${height - (data[0].usage / 100) * height} L ${points.join(' L ')} L ${width},${height} Z`;
    };

    const generateLinePath = (data: { usage: number }[], width: number, height: number) => {
        if (!data || data.length === 0) return '';
        return data.map((point, i) => {
            const x = (i / (data.length - 1)) * width;
            const y = height - (point.usage / 100) * height;
            return `${i === 0 ? 'M' : 'L'} ${x},${y}`;
        }).join(' ');
    };

    return (
        <AppLayout
            title={currentTenant?.name || t('space.dashboard.title_default')}
            navigationGroups={navGroups}
            activeItem={activeTab}
            contextInfo={{ tenantName: currentTenant?.name }}
            backButton={BackButton}
            breadcrumbs={[t('space.dashboard.breadcrumbs.home'), activeTab.charAt(0).toUpperCase() + activeTab.slice(1)]}
        >
            {activeTab === 'overview' && stats && (
                <div className="max-w-7xl mx-auto flex flex-col gap-8">
                    {/* Page Heading */}
                    <div className="flex flex-col gap-1">
                        <h2 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">{t('space.dashboard.welcome.title')}</h2>
                        <p className="text-gray-500 dark:text-slate-400">{t('space.dashboard.welcome.subtitle')}</p>
                    </div>

                    {/* Stats Cards (Gradient) */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        {/* Card 1: Total Storage */}
                        <div className="relative overflow-hidden rounded-xl p-6 shadow-lg bg-gradient-to-br from-[#1e3fae] to-[#3b82f6] text-white group hover:shadow-xl transition-shadow duration-300">
                            <div className="absolute right-0 top-0 h-full w-1/2 bg-white/5 skew-x-12 -mr-10"></div>
                            <div className="relative z-10 flex flex-col justify-between h-full gap-4">
                                <div className="flex items-start justify-between">
                                    <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                                        <Database className="h-6 w-6 text-white" />
                                    </div>
                                    <span className="text-xs font-medium bg-white/20 px-2 py-1 rounded text-white backdrop-blur-sm">+12%</span>
                                </div>
                                <div>
                                    <p className="text-blue-100 text-sm font-medium mb-1">{t('space.dashboard.stats.storage.title')}</p>
                                    <div className="flex items-baseline gap-2">
                                        <h3 className="text-3xl font-bold tracking-tight">{(stats.storage.used / (1024 * 1024 * 1024 * 1024)).toFixed(1)} TB</h3>
                                        <span className="text-blue-200 text-sm">/ {(stats.storage.total / (1024 * 1024 * 1024 * 1024)).toFixed(0)} TB</span>
                                    </div>
                                </div>
                                <div className="w-full bg-black/20 rounded-full h-1.5 mt-1">
                                    <div className="bg-white h-1.5 rounded-full" style={{ width: `${stats.storage.percentage}%` }}></div>
                                </div>
                            </div>
                        </div>

                        {/* Card 2: Active Projects */}
                        <div className="relative overflow-hidden rounded-xl p-6 shadow-lg bg-gradient-to-br from-indigo-600 to-violet-500 text-white group hover:shadow-xl transition-shadow duration-300">
                            <div className="absolute right-0 top-0 h-full w-1/2 bg-white/5 skew-x-12 -mr-10"></div>
                            <div className="relative z-10 flex flex-col justify-between h-full gap-4">
                                <div className="flex items-start justify-between">
                                    <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                                        <FolderOpen className="h-6 w-6 text-white" />
                                    </div>
                                    <span className="text-xs font-medium bg-white/20 px-2 py-1 rounded text-white backdrop-blur-sm">{stats.projects.active} Active</span>
                                </div>
                                <div>
                                    <p className="text-indigo-100 text-sm font-medium mb-1">{t('space.dashboard.stats.projects.title')}</p>
                                    <h3 className="text-3xl font-bold tracking-tight">{stats.projects.active}</h3>
                                </div>
                                <p className="text-indigo-100 text-sm">{t('space.dashboard.stats.projects.new_this_week', { count: stats.projects.new_this_week })}</p>
                            </div>
                        </div>

                        {/* Card 3: Team Members */}
                        <div className="relative overflow-hidden rounded-xl p-6 shadow-lg bg-gradient-to-br from-slate-700 to-slate-600 text-white group hover:shadow-xl transition-shadow duration-300">
                            <div className="absolute right-0 top-0 h-full w-1/2 bg-white/5 skew-x-12 -mr-10"></div>
                            <div className="relative z-10 flex flex-col justify-between h-full gap-4">
                                <div className="flex items-start justify-between">
                                    <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                                        <Users className="h-6 w-6 text-white" />
                                    </div>
                                    <span className="text-xs font-medium bg-white/20 px-2 py-1 rounded text-white backdrop-blur-sm">{t('space.dashboard.stats.members.total_badge', { count: stats.members.total })}</span>
                                </div>
                                <div>
                                    <p className="text-slate-200 text-sm font-medium mb-1">{t('space.dashboard.stats.members.title')}</p>
                                    <h3 className="text-3xl font-bold tracking-tight">{stats.members.total}</h3>
                                </div>
                                <div className="flex -space-x-2 overflow-hidden mt-1">
                                    {[1, 2, 3].map((i) => (
                                        <div key={i} className="inline-block h-6 w-6 rounded-full ring-2 ring-slate-600 bg-gray-400 flex items-center justify-center text-xs font-medium text-white">
                                            U{i}
                                        </div>
                                    ))}
                                    <div className="h-6 w-6 rounded-full bg-slate-500 ring-2 ring-slate-600 flex items-center justify-center text-[10px] font-medium text-white">+{stats.members.new_added}</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Middle Row: Chart & Tenant Info */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                        {/* Main Chart Area */}
                        <div className="lg:col-span-2 bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-gray-200 dark:border-slate-800 p-6 flex flex-col">
                            <div className="flex justify-between items-center mb-6">
                                <div>
                                    <h3 className="text-lg font-bold text-gray-900 dark:text-white">{t('space.dashboard.charts.memory_usage.title')}</h3>
                                    <p className="text-sm text-gray-500 dark:text-slate-400">{t('space.dashboard.charts.memory_usage.subtitle')}</p>
                                </div>
                                <select className="form-select bg-gray-50 dark:bg-slate-800 border-gray-200 dark:border-slate-700 text-gray-700 dark:text-slate-300 text-sm rounded-lg py-1.5 px-3 focus:ring-blue-500 focus:border-blue-500">
                                    <option>{t('space.dashboard.charts.memory_usage.period.30d')}</option>
                                    <option>{t('space.dashboard.charts.memory_usage.period.7d')}</option>
                                    <option>{t('space.dashboard.charts.memory_usage.period.24h')}</option>
                                </select>
                            </div>

                            {/* Simulated Chart using SVG */}
                            <div className="flex-1 w-full min-h-[240px] relative">
                                {/* Grid Lines */}
                                <div className="absolute inset-0 flex flex-col justify-between text-xs text-gray-400 dark:text-slate-500">
                                    {[100, 75, 50, 25, 0].map((val) => (
                                        <div key={val} className="flex w-full items-center">
                                            <span className="w-8 text-right pr-2">{val}%</span>
                                            <div className="h-px bg-gray-100 dark:bg-slate-700 flex-1"></div>
                                        </div>
                                    ))}
                                </div>
                                {/* Chart Curve */}
                                <svg className="absolute inset-0 h-full w-full pl-8 pb-4 pt-2" preserveAspectRatio="none" viewBox="0 0 800 300">
                                    <defs>
                                        <linearGradient id="chartGradient" x1="0" x2="0" y1="0" y2="1">
                                            <stop offset="0%" stopColor="#1e3fae" stopOpacity="0.2"></stop>
                                            <stop offset="100%" stopColor="#1e3fae" stopOpacity="0"></stop>
                                        </linearGradient>
                                    </defs>
                                    <path d={generatePath(stats.memory_history, 800, 300)} fill="url(#chartGradient)"></path>
                                    <path d={generateLinePath(stats.memory_history, 800, 300)} fill="none" stroke="#1e3fae" strokeWidth="2" vectorEffect="non-scaling-stroke"></path>
                                </svg>
                                {/* X-Axis Labels */}
                                <div className="absolute bottom-0 left-8 right-0 flex justify-between text-xs text-gray-400 dark:text-slate-500 pt-2">
                                    {stats.memory_history.filter((_: any, i: number) => i % 7 === 0).map((point: any) => (
                                        <span key={point.date}>{point.date}</span>
                                    ))}
                                </div>
                            </div>
                        </div>

                        {/* Tenant Details */}
                        <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-gray-200 dark:border-slate-800 p-6">
                            <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-6">{t('space.dashboard.tenant_info.title')}</h3>
                            <div className="flex flex-col gap-6">
                                <div className="flex items-center gap-4">
                                    <div className="bg-blue-50 dark:bg-blue-900/20 p-3 rounded-lg text-blue-600 dark:text-blue-400">
                                        <Badge className="h-6 w-6" />
                                    </div>
                                    <div>
                                        <p className="text-xs font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider">{t('space.dashboard.tenant_info.org_id')}</p>
                                        <p className="text-gray-900 dark:text-white font-mono font-medium">{stats.tenant_info.organization_id}</p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-4">
                                    <div className="bg-purple-50 dark:bg-purple-900/20 p-3 rounded-lg text-purple-600 dark:text-purple-400">
                                        <Database className="h-6 w-6" />
                                    </div>
                                    <div>
                                        <p className="text-xs font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider">{t('space.dashboard.tenant_info.plan')}</p>
                                        <p className="text-gray-900 dark:text-white font-medium capitalize">{stats.tenant_info.plan}</p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-4">
                                    <div className="bg-emerald-50 dark:bg-emerald-900/20 p-3 rounded-lg text-emerald-600 dark:text-emerald-400">
                                        <Globe className="h-6 w-6" />
                                    </div>
                                    <div>
                                        <p className="text-xs font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider">{t('space.dashboard.tenant_info.region')}</p>
                                        <p className="text-gray-900 dark:text-white font-medium">{stats.tenant_info.region}</p>
                                    </div>
                                </div>
                                <div className="h-px w-full bg-gray-100 dark:bg-slate-800 my-2"></div>
                                <div className="bg-gray-50 dark:bg-slate-800 rounded-lg p-4 border border-gray-100 dark:border-slate-700">
                                    <div className="flex justify-between items-center mb-2">
                                        <span className="text-sm text-gray-500 dark:text-slate-400">{t('space.dashboard.tenant_info.next_billing')}</span>
                                        <span className="text-sm font-semibold text-gray-900 dark:text-white">{stats.tenant_info.next_billing_date}</span>
                                    </div>
                                    <button className="w-full py-2 px-4 bg-white dark:bg-slate-700 border border-gray-200 dark:border-slate-600 rounded-md text-sm font-medium text-gray-700 dark:text-slate-200 hover:bg-gray-50 dark:hover:bg-slate-600 transition-colors">
                                        {t('space.dashboard.tenant_info.view_invoice')}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Bottom Row: Recent Active Projects */}
                    <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-gray-200 dark:border-slate-800 flex flex-col overflow-hidden">
                        <div className="p-6 border-b border-gray-100 dark:border-slate-800 flex flex-wrap gap-4 items-center justify-between">
                            <h3 className="text-lg font-bold text-gray-900 dark:text-white">{t('space.dashboard.active_projects.title')}</h3>
                            <button onClick={() => setActiveTab('projects')} className="text-blue-600 dark:text-blue-400 text-sm font-medium hover:underline">{t('space.dashboard.active_projects.view_all')}</button>
                        </div>
                        <div className="overflow-x-auto">
                            <table className="w-full text-left border-collapse">
                                <thead>
                                    <tr className="bg-gray-50 dark:bg-slate-800 border-b border-gray-100 dark:border-slate-800">
                                        <th className="py-4 px-6 text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider">{t('space.dashboard.active_projects.table.name')}</th>
                                        <th className="py-4 px-6 text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider">{t('space.dashboard.active_projects.table.owner')}</th>
                                        <th className="py-4 px-6 text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider">{t('space.dashboard.active_projects.table.memory')}</th>
                                        <th className="py-4 px-6 text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider text-right">{t('space.dashboard.active_projects.table.status')}</th>
                                        <th className="py-4 px-6 text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider text-right">{t('space.dashboard.active_projects.table.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
                                    {stats.projects.list.map((project: any, index: number) => (
                                        <tr key={project.id} className="hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors">
                                            <td className="py-4 px-6">
                                                <div className="flex items-center gap-3">
                                                    <div className={`p-2 rounded-lg ${index % 3 === 0 ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' : index % 3 === 1 ? 'bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400' : 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400'}`}>
                                                        {index % 3 === 0 ? <Cpu className="h-5 w-5" /> : index % 3 === 1 ? <Cloud className="h-5 w-5" /> : <Beaker className="h-5 w-5" />}
                                                    </div>
                                                    <div>
                                                        <p className="font-medium text-gray-900 dark:text-white cursor-pointer hover:text-blue-600 dark:hover:text-blue-400" onClick={() => navigate(`/space/${spaceId}/project/${project.id}`)}>{project.name}</p>
                                                        <p className="text-xs text-gray-500 dark:text-slate-500">ID: #{project.id.substring(0, 8)}</p>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="py-4 px-6">
                                                <div className="flex items-center gap-2">
                                                    <div className="h-6 w-6 rounded-full bg-gray-200 dark:bg-slate-700 flex items-center justify-center text-xs font-bold text-gray-600 dark:text-slate-300">
                                                        {project.owner.charAt(0)}
                                                    </div>
                                                    <span className="text-sm text-gray-700 dark:text-slate-300">{project.owner}</span>
                                                </div>
                                            </td>
                                            <td className="py-4 px-6">
                                                <div className="flex items-center gap-2">
                                                    <div className="w-24 bg-gray-100 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                                                        <div className="bg-blue-600 h-1.5 rounded-full" style={{ width: `${(index * 37) % 80 + 20}%` }}></div>
                                                    </div>
                                                    <span className="text-sm font-medium text-gray-700 dark:text-slate-300">{project.memory_consumed}</span>
                                                </div>
                                            </td>
                                            <td className="py-4 px-6 text-right">
                                                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${project.status === 'Active' ? 'bg-emerald-100 dark:bg-emerald-900/20 text-emerald-800 dark:text-emerald-400' : 'bg-amber-100 dark:bg-amber-900/20 text-amber-800 dark:text-amber-400'}`}>
                                                    <span className={`h-1.5 w-1.5 rounded-full ${project.status === 'Active' ? 'bg-emerald-500' : 'bg-amber-500'}`}></span>
                                                    {project.status}
                                                </span>
                                            </td>
                                            <td className="py-4 px-6 text-right">
                                                <button className="text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
                                                    <MoreVertical className="h-5 w-5" />
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'projects' && (
                <div className="max-w-7xl mx-auto">
                    <div className="flex justify-between items-center mb-6">
                        <div>
                            <h2 className="text-xl font-bold text-gray-900 dark:text-white">{t('space.dashboard.projects_tab.title')}</h2>
                            <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">{t('space.dashboard.projects_tab.subtitle')}</p>
                        </div>
                        <button
                            onClick={() => setIsCreateProjectOpen(true)}
                            className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
                        >
                            <Plus className="h-4 w-4" />
                            <span>{t('space.dashboard.projects_tab.new_project')}</span>
                        </button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                        {projects.map((project) => (
                            <div
                                key={project.id}
                                onClick={() => handleEnterProject(project)}
                                className="group bg-white dark:bg-surface-dark rounded-lg border border-gray-200 dark:border-slate-800 hover:shadow-md hover:border-blue-300 dark:hover:border-blue-500 transition-all cursor-pointer flex flex-col h-full"
                            >
                                <div className="p-5 flex-1">
                                    <div className="flex justify-between items-start mb-3">
                                        <div className="p-2 bg-green-50 dark:bg-green-900/20 rounded-lg">
                                            <Folder className="h-6 w-6 text-green-600 dark:text-green-400" />
                                        </div>
                                    </div>
                                    <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-2 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors truncate">
                                        {project.name}
                                    </h3>
                                    <p className="text-sm text-gray-500 dark:text-slate-400 line-clamp-3 mb-4 h-10">
                                        {project.description || t('space.dashboard.projects_tab.no_description')}
                                    </p>
                                </div>

                                <div className="px-5 py-3 bg-gray-50 dark:bg-slate-800 border-t border-gray-100 dark:border-slate-800 rounded-b-lg flex items-center justify-between text-xs text-gray-500 dark:text-slate-500">
                                    <span>{new Date(project.created_at).toLocaleDateString()}</span>
                                    <span>{t('space.dashboard.projects_tab.member_count', { count: 1 })}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                    <ProjectCreateModal
                        isOpen={isCreateProjectOpen}
                        onClose={() => setIsCreateProjectOpen(false)}
                        onSuccess={() => listProjects(spaceId!)}
                    />
                </div>
            )}

            {/* Other Tabs */}
            {(activeTab === 'users' || activeTab === 'analytics' || activeTab === 'billing' || activeTab === 'settings') && (
                <div className="flex flex-col items-center justify-center py-20 text-center">
                    <div className="p-4 bg-gray-100 dark:bg-slate-800 rounded-full mb-4">
                        <Settings className="h-8 w-8 text-gray-400 dark:text-slate-500" />
                    </div>
                    <h3 className="text-lg font-medium text-gray-900 dark:text-white">{t('space.dashboard.coming_soon.title')}</h3>
                    <p className="text-gray-500 dark:text-slate-400 max-w-sm mt-1">
                        {t('space.dashboard.coming_soon.desc', { module: activeTab.charAt(0).toUpperCase() + activeTab.slice(1) })}
                    </p>
                </div>
            )}
        </AppLayout>
    );
};
