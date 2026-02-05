import React, { useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Plus, Building2, ArrowRight } from 'lucide-react';

import { useModal } from '@/hooks/useModal';

import { AppLayout, NavigationItem } from '@/components/shared/layouts/AppLayout';
import { TenantCreateModal } from '@/components/tenant/TenantCreateModal';

import { useTenantStore } from '../stores/tenant';
import { Tenant } from '../types/memory';

export const SpaceListPage: React.FC = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { tenants, listTenants, setCurrentTenant } = useTenantStore();
    const createModal = useModal();

    useEffect(() => {
        listTenants();
    }, [listTenants]);

    const handleEnterSpace = (tenant: Tenant) => {
        setCurrentTenant(tenant);
        navigate(`/space/${tenant.id}`);
    };

    const navItems: NavigationItem[] = [
        { id: 'spaces', label: t('space.list.title'), icon: Building2, onClick: () => { } },
        // { id: 'settings', label: t('nav.settings'), icon: Settings, onClick: () => navigate('/settings') }
    ];

    return (
        <AppLayout
            title={t('space.list.title')}
            navigationItems={navItems}
            activeItem="spaces"
        >
            <div className="max-w-7xl mx-auto">
                <div className="flex justify-between items-center mb-8">
                    <div>
                        <h2 className="text-2xl font-bold text-gray-900">{t('space.list.welcome.title')}</h2>
                        <p className="mt-1 text-gray-500">{t('space.list.welcome.subtitle')}</p>
                    </div>
                    <button
                        onClick={() => createModal.open()}
                        className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
                    >
                        <Plus className="h-5 w-5" />
                        <span>{t('space.list.create_button')}</span>
                    </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {tenants.map((tenant) => (
                        <div
                            key={tenant.id}
                            onClick={() => handleEnterSpace(tenant)}
                            className="group bg-white rounded-xl border border-gray-200 p-6 hover:shadow-lg hover:border-blue-300 transition-all cursor-pointer relative overflow-hidden"
                        >
                            <div className="absolute top-0 right-0 p-4 opacity-0 group-hover:opacity-100 transition-opacity">
                                <ArrowRight className="h-5 w-5 text-blue-500" />
                            </div>

                            <div className="flex items-start justify-between mb-4">
                                <div className="p-3 bg-blue-50 rounded-lg">
                                    <Building2 className="h-8 w-8 text-blue-600" />
                                </div>
                                <span className={`px-2 py-1 text-xs font-medium rounded-full ${tenant.plan === 'free' ? 'bg-gray-100 text-gray-600' : 'bg-purple-100 text-purple-600'
                                    }`}>
                                    {tenant.plan.toUpperCase()}
                                </span>
                            </div>

                            <h3 className="text-lg font-bold text-gray-900 mb-2 group-hover:text-blue-600 transition-colors">
                                {tenant.name}
                            </h3>
                            <p className="text-sm text-gray-500 mb-6 line-clamp-2 h-10">
                                {tenant.description || t('space.list.card.no_description')}
                            </p>

                            <div className="flex items-center justify-between text-sm text-gray-500 border-t border-gray-100 pt-4">
                                <div className="flex flex-col">
                                    <span className="font-semibold text-gray-900">{tenant.max_projects}</span>
                                    <span className="text-xs">{t('space.list.card.max_projects')}</span>
                                </div>
                                <div className="flex flex-col text-right">
                                    <span className="font-semibold text-gray-900">{tenant.max_users}</span>
                                    <span className="text-xs">{t('space.list.card.max_users')}</span>
                                </div>
                            </div>
                        </div>
                    ))}

                    {/* Empty State Create Card */}
                    {tenants.length === 0 && (
                        <div
                            onClick={() => createModal.open()}
                            className="flex flex-col items-center justify-center p-8 border-2 border-dashed border-gray-300 rounded-xl hover:border-blue-400 hover:bg-blue-50 transition-all cursor-pointer h-full min-h-[240px]"
                        >
                            <div className="p-4 bg-gray-100 rounded-full mb-4">
                                <Plus className="h-8 w-8 text-gray-400" />
                            </div>
                            <h3 className="text-lg font-medium text-gray-900">{t('space.list.empty.title')}</h3>
                            <p className="text-sm text-gray-500 mt-2 text-center">{t('space.list.empty.subtitle')}</p>
                        </div>
                    )}
                </div>

                <TenantCreateModal
                    isOpen={createModal.isOpen}
                    onClose={() => createModal.close()}
                    onSuccess={() => listTenants()}
                />
            </div>
        </AppLayout>
    );
};
