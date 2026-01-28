import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
    Brain,
    Network,
    Settings,
    ArrowLeft,
    LayoutDashboard
} from 'lucide-react';
import { AppLayout, NavigationItem } from '@/components/shared/layouts/AppLayout';
import { useTenantStore } from '../stores/tenant';
import { useProjectStore } from '../stores/project';
import { MemoryManager } from '@/components/project/MemoryManager';
import { GraphVisualization } from '@/components/graph/GraphVisualization';
import { Overview } from '../components/workbench/Overview';

export const ProjectDashboard: React.FC = () => {
    const { t } = useTranslation();
    const { spaceId, projectId } = useParams<{ spaceId: string; projectId: string }>();
    const navigate = useNavigate();
    const { currentTenant, getTenant } = useTenantStore();
    const { currentProject, getProject } = useProjectStore();

    // Local state for active tab (sub-route simulation)
    // Ideally this should be handled by nested routes like /.../memories
    const [activeTab, setActiveTab] = useState('overview');

    useEffect(() => {
        if (spaceId && !currentTenant) {
            getTenant(spaceId);
        }
        if (spaceId && projectId) {
            getProject(spaceId, projectId);
        }
    }, [spaceId, projectId, currentTenant, getTenant, getProject]);

    const navItems: NavigationItem[] = [
        { id: 'overview', label: t('nav.overview') || 'Overview', icon: LayoutDashboard, onClick: () => setActiveTab('overview') },
        { id: 'memories', label: t('dashboard.project.memories.title'), icon: Brain, onClick: () => setActiveTab('memories') },
        { id: 'graph', label: t('dashboard.project.graph.title'), icon: Network, onClick: () => setActiveTab('graph') },
        { id: 'settings', label: t('nav.settings'), icon: Settings, onClick: () => setActiveTab('settings') },
    ];

    const BackButton = (
        <button
            onClick={() => navigate(`/space/${spaceId}`)}
            className="p-1 hover:bg-blue-700 rounded transition-colors mr-2"
            title={t('dashboard.project.back_button_title')}
        >
            <ArrowLeft className="h-5 w-5 text-white" />
        </button>
    );

    return (
        <AppLayout
            title={currentProject?.name || t('dashboard.project.title_loading')}
            navigationItems={navItems}
            activeItem={activeTab}
            contextInfo={{
                tenantName: currentTenant?.name,
                projectName: currentProject?.name
            }}
            backButton={BackButton}
        >
            {activeTab === 'overview' && (
                <Overview onNavigate={(tab) => setActiveTab(tab)} />
            )}

            {activeTab === 'memories' && (
                <div className="space-y-6">
                    <div className="flex items-center justify-between">
                        <h2 className="text-2xl font-bold text-gray-900">{t('dashboard.project.memories.title')}</h2>
                    </div>
                    <MemoryManager />
                </div>
            )}

            {activeTab === 'graph' && (
                <div className="space-y-6 h-full flex flex-col">
                    <div className="flex items-center justify-between">
                        <h2 className="text-2xl font-bold text-gray-900">{t('dashboard.project.graph.title')}</h2>
                    </div>
                    <div className="flex-1 bg-white rounded-lg shadow-sm border border-gray-200 min-h-[600px]">
                        <GraphVisualization />
                    </div>
                </div>
            )}

            {activeTab === 'settings' && (
                <div className="text-center py-20 text-gray-500">
                    <Settings className="h-12 w-12 mx-auto mb-4 text-gray-300" />
                    <p className="text-lg">{t('dashboard.project.settings.development')}</p>
                </div>
            )}
        </AppLayout>
    );
};
