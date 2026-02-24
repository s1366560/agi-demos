import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { formatDateOnly } from '@/utils/date';

import { useTenantStore } from '../../stores/tenant';

import type { UserTenant } from '../../types/memory';

interface TenantMember {
  user_id: string;
  email: string;
  name: string;
  role: string;
  permissions: Record<string, any>;
  created_at: string;
}

export const UserList: React.FC = () => {
  const { t } = useTranslation();
  const { currentTenant, listMembers, isLoading } = useTenantStore();
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  useEffect(() => {
    const fetchMembers = async () => {
      if (currentTenant) {
        try {
          const response = await listMembers(currentTenant.id);
          // Map UserTenant to TenantMember
          const members: TenantMember[] = response.map((member: UserTenant) => ({
            user_id: member.user_id,
            email: member.user_id, // user_id is email in this context
            name: member.user_id.split('@')[0] || member.user_id, // Extract name from email
            role: member.role,
            permissions: member.permissions,
            created_at: member.created_at,
          }));
          setMembers(members);
        } catch (error) {
          console.error('Failed to fetch members:', error);
        }
      }
    };
    fetchMembers();
  }, [currentTenant, listMembers]);

  const filteredMembers = members.filter((member) => {
    const matchesSearch =
      member.name.toLowerCase().includes(search.toLowerCase()) ||
      member.email.toLowerCase().includes(search.toLowerCase());
    const matchesRole = roleFilter === 'all' || member.role === roleFilter.toLowerCase();
    // Status is not yet in API response, assuming Active for now
    const matchesStatus = statusFilter === 'all' || 'active' === statusFilter.toLowerCase();

    return matchesSearch && matchesRole && matchesStatus;
  });

  if (!currentTenant) {
    return <div className="p-8 text-center text-slate-500">{t('tenant.overview.loading')}</div>;
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      {/* Header Area */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            {t('tenant.users.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t('tenant.users.subtitle')}</p>
        </div>
        <button className="inline-flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary">
          <span className="material-symbols-outlined text-[20px]">add</span>
          {t('tenant.users.inviteMember')}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex items-start justify-between">
          <div>
            <p className="text-sm font-medium text-slate-500 mb-1">{t('common.stats.total')}</p>
            <div className="flex items-baseline gap-2">
              <h3 className="text-3xl font-bold text-slate-900 dark:text-white">
                {members.length}
                <span className="text-lg text-slate-400 font-normal">
                  /{currentTenant.max_users}
                </span>
              </h3>
            </div>
            <div className="mt-2 w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-primary h-1.5 rounded-full"
                style={{ width: `${(members.length / currentTenant.max_users) * 100}%` }}
              ></div>
            </div>
          </div>
          <div className="p-2 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-primary">
            <span className="material-symbols-outlined">badge</span>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex items-start justify-between">
          <div>
            <p className="text-sm font-medium text-slate-500 mb-1">
              {t('common.stats.activeUsers')}
            </p>
            <h3 className="text-3xl font-bold text-slate-900 dark:text-white">{members.length}</h3>
            <p className="text-xs text-green-600 font-medium mt-1 flex items-center gap-1">
              <span className="material-symbols-outlined text-[14px]">trending_up</span>
              100% {t('common.status.active')}
            </p>
          </div>
          <div className="p-2 bg-green-50 dark:bg-green-900/20 rounded-lg text-green-600">
            <span className="material-symbols-outlined">verified_user</span>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex items-start justify-between">
          <div>
            <p className="text-sm font-medium text-slate-500 mb-1">
              {t('common.stats.pendingInvites')}
            </p>
            <h3 className="text-3xl font-bold text-slate-900 dark:text-white">0</h3>
            <p className="text-xs text-slate-400 mt-1">Awaiting acceptance</p>
          </div>
          <div className="p-2 bg-orange-50 dark:bg-orange-900/20 rounded-lg text-orange-500">
            <span className="material-symbols-outlined">mail</span>
          </div>
        </div>
      </div>

      {/* Main Content Card */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex flex-col">
        {/* Filters Toolbar */}
        <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex flex-col sm:flex-row gap-4 justify-between items-center bg-slate-50/50 dark:bg-slate-800/20">
          <div className="relative w-full sm:w-96">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <span className="material-symbols-outlined text-slate-400 text-[20px]">search</span>
            </div>
            <input
              className="block w-full pl-10 pr-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg leading-5 bg-white dark:bg-surface-dark text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary sm:text-sm"
              placeholder={t('tenant.users.searchPlaceholder')}
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); }}
            />
          </div>
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <div className="relative">
              <select
                className="appearance-none bg-white dark:bg-surface-dark border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 py-2 pl-3 pr-8 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary cursor-pointer"
                value={roleFilter}
                onChange={(e) => { setRoleFilter(e.target.value); }}
              >
                <option value="all">{t('tenant.users.allRoles')}</option>
                <option value="admin">Admin</option>
                <option value="member">Member</option>
                <option value="owner">Owner</option>
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                <span className="material-symbols-outlined text-[16px]">expand_more</span>
              </div>
            </div>
            <div className="relative">
              <select
                className="appearance-none bg-white dark:bg-surface-dark border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 py-2 pl-3 pr-8 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary cursor-pointer"
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); }}
              >
                <option value="all">{t('common.status.all')}</option>
                <option value="active">{t('common.status.active')}</option>
                <option value="pending">{t('common.status.pending')}</option>
                <option value="suspended">{t('common.status.suspended')}</option>
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                <span className="material-symbols-outlined text-[16px]">expand_more</span>
              </div>
            </div>
            <button className="p-2 text-slate-400 hover:text-slate-600 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-surface-dark">
              <span className="material-symbols-outlined text-[20px]">filter_list</span>
            </button>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
            <thead className="bg-slate-50 dark:bg-slate-800">
              <tr>
                <th
                  className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider w-1/3"
                  scope="col"
                >
                  User
                </th>
                <th
                  className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                  scope="col"
                >
                  {t('common.forms.role')}
                </th>
                <th
                  className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                  scope="col"
                >
                  Joined
                </th>
                <th
                  className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                  scope="col"
                >
                  {t('common.forms.status')}
                </th>
                <th className="relative px-6 py-3" scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="bg-surface-light dark:bg-surface-dark divide-y divide-slate-200 dark:divide-slate-700">
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-500">
                    {t('tenant.users.loading') || 'Loading members...'}
                  </td>
                </tr>
              ) : filteredMembers.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-500">
                    {t('tenant.users.noMembers')}
                  </td>
                </tr>
              ) : (
                filteredMembers.map((member) => (
                  <tr
                    key={member.user_id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <div className="flex-shrink-0 h-10 w-10 bg-primary/10 rounded-full flex items-center justify-center text-primary font-bold">
                          {member.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="ml-4">
                          <div className="text-sm font-medium text-slate-900 dark:text-white">
                            {member.name}
                          </div>
                          <div className="text-sm text-slate-500">{member.email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          member.role === 'owner'
                            ? 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300'
                            : member.role === 'admin'
                              ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'
                              : 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {member.role.charAt(0).toUpperCase() + member.role.slice(1)}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
                      {formatDateOnly(member.created_at)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                        <span className="h-1.5 w-1.5 rounded-full bg-green-500"></span>{' '}
                        {t('common.status.active')}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button className="text-slate-400 hover:text-primary transition-colors">
                        <span className="material-symbols-outlined">more_vert</span>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {/* Pagination (Mocked for now) */}
        <div className="px-4 py-3 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between sm:px-6">
          <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
            <div>
              <p className="text-sm text-slate-700 dark:text-slate-400">
                {t('tenant.users.showingResults', {
                  start: 1,
                  end: filteredMembers.length,
                  total: filteredMembers.length,
                })}
              </p>
            </div>
            <div>
              <nav
                aria-label="Pagination"
                className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px"
              >
                <button className="relative inline-flex items-center px-2 py-2 rounded-l-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-surface-dark text-sm font-medium text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-700">
                  <span className="sr-only">Previous</span>
                  <span className="material-symbols-outlined text-[20px]">chevron_left</span>
                </button>
                <button
                  aria-current="page"
                  className="z-10 bg-primary/10 border-primary text-primary relative inline-flex items-center px-4 py-2 border text-sm font-medium"
                >
                  1
                </button>
                <button className="relative inline-flex items-center px-2 py-2 rounded-r-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-surface-dark text-sm font-medium text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-700">
                  <span className="sr-only">Next</span>
                  <span className="material-symbols-outlined text-[20px]">chevron_right</span>
                </button>
              </nav>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
