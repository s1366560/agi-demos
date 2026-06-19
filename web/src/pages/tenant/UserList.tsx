import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import {
  BadgeCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Filter,
  Mail,
  MoreVertical,
  Plus,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useTenantStore } from '@/stores/tenant';

import { invitationService } from '@/services/invitationService';

import { confirmAction } from '@/utils/confirmAction';
import { formatDateOnly } from '@/utils/date';

import type { UserTenant } from '@/types/memory';

const PAGE_SIZE = 10;
const ROLE_FILTERS = ['owner', 'admin', 'member', 'viewer', 'editor', 'guest'];
const INVITE_ROLES = ['admin', 'member', 'viewer', 'editor'];

interface TenantMember {
  user_id: string;
  email: string;
  name: string;
  role: string;
  permissions: Record<string, unknown>;
  created_at: string;
}

type TenantMemberRecord = Omit<UserTenant, 'created_at' | 'permissions'> & {
  created_at?: string | undefined;
  email?: string | undefined;
  name?: string | undefined;
  full_name?: string | undefined;
  permissions?: Record<string, unknown> | undefined;
};

function normalizeMembersPayload(response: unknown): TenantMemberRecord[] {
  if (Array.isArray(response)) {
    return response as TenantMemberRecord[];
  }

  if (response && typeof response === 'object') {
    const members = (response as { members?: unknown }).members;
    if (Array.isArray(members)) {
      return members as TenantMemberRecord[];
    }
  }

  return [];
}

function normalizeMember(member: TenantMemberRecord): TenantMember {
  const email = member.email ?? member.user_email ?? member.user_id;
  const fallbackName = (email.includes('@') ? email.split('@')[0] : email) ?? email;
  const name = member.name ?? member.full_name ?? member.user_name ?? fallbackName;

  return {
    user_id: member.user_id,
    email,
    name: name.trim() || email,
    role: member.role,
    permissions: member.permissions ?? {},
    created_at: member.created_at ?? member.joined_at ?? '',
  };
}

function formatFallbackRole(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export const UserList: React.FC = () => {
  const { t } = useTranslation();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string | undefined }>();
  const { currentTenant, listMembers, removeMember, isLoading } = useTenantStore(
    useShallow((state) => ({
      currentTenant: state.currentTenant,
      listMembers: state.listMembers,
      removeMember: state.removeMember,
      isLoading: state.isLoading,
    }))
  );
  const tenantId = routeTenantId ?? currentTenant?.id ?? null;
  const tenantForLimits = currentTenant?.id === tenantId ? currentTenant : null;
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pendingInvites, setPendingInvites] = useState(0);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [isInviteOpen, setIsInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [inviteMessage, setInviteMessage] = useState('');
  const [inviteLoading, setInviteLoading] = useState(false);
  const [openActionUserId, setOpenActionUserId] = useState<string | null>(null);
  const [removingUserId, setRemovingUserId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; message: string } | null>(null);

  const loadMembers = React.useCallback(async () => {
    if (!tenantId) {
      setMembers([]);
      return;
    }

    try {
      const response = await listMembers(tenantId);
      setMembers(normalizeMembersPayload(response).map(normalizeMember));
    } catch (error) {
      console.error('Failed to fetch members:', error);
      setNotice({ kind: 'error', message: t('tenant.users.load_error') });
    }
  }, [listMembers, tenantId, t]);

  const loadPendingInvitations = React.useCallback(async () => {
    if (!tenantId) {
      setPendingInvites(0);
      return;
    }

    setPendingLoading(true);
    try {
      const response = await invitationService.listPending(tenantId);
      setPendingInvites(response.total);
    } catch (error) {
      console.error('Failed to fetch pending invitations:', error);
      setPendingInvites(0);
    } finally {
      setPendingLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void loadMembers();
    void loadPendingInvitations();
  }, [loadMembers, loadPendingInvitations]);

  useEffect(() => {
    setPage(1);
  }, [search, roleFilter]);

  const filteredMembers = members.filter((member) => {
    const query = search.trim().toLowerCase();
    const matchesSearch =
      query.length === 0 ||
      `${member.name} ${member.email} ${member.role}`.toLowerCase().includes(query);
    const matchesRole = roleFilter === 'all' || member.role.toLowerCase() === roleFilter;

    return matchesSearch && matchesRole;
  });

  const totalPages = Math.max(Math.ceil(filteredMembers.length / PAGE_SIZE), 1);
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const visibleMembers = filteredMembers.slice(pageStart, pageStart + PAGE_SIZE);
  const resultStart = filteredMembers.length === 0 ? 0 : pageStart + 1;
  const resultEnd = Math.min(pageStart + PAGE_SIZE, filteredMembers.length);
  const hasFilters = search.trim().length > 0 || roleFilter !== 'all';
  const privilegedMembers = members.filter((member) =>
    ['owner', 'admin'].includes(member.role.toLowerCase())
  ).length;

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const getRoleLabel = (role: string) =>
    t(`tenant.users.roles.${role}`, { defaultValue: formatFallbackRole(role) });

  const clearFilters = () => {
    setSearch('');
    setRoleFilter('all');
  };

  const handleInviteSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tenantId || inviteEmail.trim().length === 0) return;

    setInviteLoading(true);
    setNotice(null);
    try {
      const message = inviteMessage.trim();
      await invitationService.create(tenantId, {
        email: inviteEmail.trim(),
        role: inviteRole,
        ...(message ? { message } : {}),
      });
      setInviteEmail('');
      setInviteRole('member');
      setInviteMessage('');
      setIsInviteOpen(false);
      setNotice({ kind: 'success', message: t('tenant.users.invite_success') });
      await loadPendingInvitations();
    } catch (error) {
      console.error('Failed to invite member:', error);
      setNotice({ kind: 'error', message: t('tenant.users.invite_error') });
    } finally {
      setInviteLoading(false);
    }
  };

  const handleRemoveMember = async (member: TenantMember) => {
    if (!tenantId || member.role === 'owner') return;
    const confirmed = await confirmAction({
      title: t('tenant.users.remove_confirm'),
      danger: true,
    });
    if (!confirmed) return;

    setRemovingUserId(member.user_id);
    setNotice(null);
    try {
      await removeMember(tenantId, member.user_id);
      setOpenActionUserId(null);
      setNotice({ kind: 'success', message: t('tenant.users.remove_success') });
      await loadMembers();
    } catch (error) {
      console.error('Failed to remove member:', error);
      setNotice({ kind: 'error', message: t('tenant.users.remove_error') });
    } finally {
      setRemovingUserId(null);
    }
  };

  if (!tenantId) {
    return <div className="p-8 text-center text-slate-500">{t('tenant.overview.loading')}</div>;
  }

  const maxUsers = Math.max(tenantForLimits?.max_users || members.length || 1, 1);
  const usagePercent = Math.min((members.length / maxUsers) * 100, 100);

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            {t('tenant.users.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t('tenant.users.subtitle')}</p>
        </div>
        <button
          className="inline-flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary"
          type="button"
          onClick={() => {
            setIsInviteOpen((open) => !open);
          }}
        >
          <Plus size={20} />
          {t('tenant.users.inviteMember')}
        </button>
      </div>

      {notice ? (
        <div
          className={`rounded-lg border px-4 py-3 text-sm ${
            notice.kind === 'success'
              ? 'border-green-200 bg-green-50 text-green-700 dark:border-green-900/50 dark:bg-green-900/20 dark:text-green-300'
              : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-900/20 dark:text-red-300'
          }`}
          role="status"
        >
          {notice.message}
        </div>
      ) : null}

      {isInviteOpen ? (
        <form
          className="rounded-lg border border-slate-200 bg-surface-light p-4 shadow-sm dark:border-slate-700 dark:bg-surface-dark"
          onSubmit={(event) => {
            void handleInviteSubmit(event);
          }}
        >
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_180px]">
            <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('tenant.users.invite_modal.email')}
              <input
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-primary focus:ring-1 focus:ring-primary dark:border-slate-600 dark:bg-surface-dark dark:text-white"
                placeholder={t('tenant.users.invite_modal.email_placeholder')}
                required
                type="email"
                value={inviteEmail}
                onChange={(event) => {
                  setInviteEmail(event.target.value);
                }}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
              {t('tenant.users.invite_modal.role')}
              <select
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-primary focus:ring-1 focus:ring-primary dark:border-slate-600 dark:bg-surface-dark dark:text-white"
                value={inviteRole}
                onChange={(event) => {
                  setInviteRole(event.target.value);
                }}
              >
                {INVITE_ROLES.map((role) => (
                  <option key={role} value={role}>
                    {getRoleLabel(role)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="mt-4 flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
            {t('tenant.users.invite_modal.message')}
            <textarea
              className="min-h-20 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-primary focus:ring-1 focus:ring-primary dark:border-slate-600 dark:bg-surface-dark dark:text-white"
              placeholder={t('tenant.users.invite_modal.message_placeholder')}
              value={inviteMessage}
              onChange={(event) => {
                setInviteMessage(event.target.value);
              }}
            />
          </label>
          <div className="mt-4 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-600 dark:bg-surface-dark dark:text-slate-200 dark:hover:bg-slate-800"
              type="button"
              onClick={() => {
                setIsInviteOpen(false);
              }}
            >
              {t('tenant.users.invite_modal.cancel')}
            </button>
            <button
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-60"
              disabled={inviteLoading}
              type="submit"
            >
              <Mail size={16} />
              {inviteLoading ? t('tenant.users.saving') : t('tenant.users.invite_modal.submit')}
            </button>
          </div>
        </form>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex items-start justify-between">
          <div>
            <p className="text-sm font-medium text-slate-500 mb-1">{t('common.stats.total')}</p>
            <div className="flex items-baseline gap-2">
              <h3 className="text-3xl font-bold text-slate-900 dark:text-white">
                {members.length}
                <span className="text-lg text-slate-400 font-normal">/{maxUsers}</span>
              </h3>
            </div>
            <div className="mt-2 w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-primary h-1.5 rounded-full"
                style={{ width: `${String(usagePercent)}%` }}
              />
            </div>
          </div>
          <div className="p-2 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-primary">
            <BadgeCheck size={16} />
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex items-start justify-between">
          <div>
            <p className="text-sm font-medium text-slate-500 mb-1">
              {t('tenant.users.stats.adminAccess')}
            </p>
            <h3 className="text-3xl font-bold text-slate-900 dark:text-white">
              {privilegedMembers}
            </h3>
            <p className="text-xs text-slate-500 mt-1">{t('tenant.users.stats.adminAccessHint')}</p>
          </div>
          <div className="p-2 bg-green-50 dark:bg-green-900/20 rounded-lg text-green-600">
            <ShieldCheck size={16} />
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark p-6 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex items-start justify-between">
          <div>
            <p className="text-sm font-medium text-slate-500 mb-1">
              {t('common.stats.pendingInvites')}
            </p>
            <h3 className="text-3xl font-bold text-slate-900 dark:text-white">
              {pendingLoading ? t('common.loading') : pendingInvites}
            </h3>
            <p className="text-xs text-slate-500 mt-1">{t('tenant.users.pending_hint')}</p>
          </div>
          <div className="p-2 bg-orange-50 dark:bg-orange-900/20 rounded-lg text-orange-500">
            <Mail size={16} />
          </div>
        </div>
      </div>

      <div className="bg-surface-light dark:bg-surface-dark rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm flex flex-col">
        <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex flex-col sm:flex-row gap-4 justify-between items-center bg-slate-50/50 dark:bg-slate-800/20">
          <div className="relative w-full sm:w-96">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search size={20} className="text-slate-400" />
            </div>
            <input
              className="block w-full pl-10 pr-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg leading-5 bg-white dark:bg-surface-dark text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary sm:text-sm"
              placeholder={t('tenant.users.searchPlaceholder')}
              type="text"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
            />
          </div>
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <div className="relative">
              <select
                className="appearance-none bg-white dark:bg-surface-dark border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 py-2 pl-3 pr-8 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary cursor-pointer"
                value={roleFilter}
                onChange={(event) => {
                  setRoleFilter(event.target.value);
                }}
              >
                <option value="all">{t('tenant.users.allRoles')}</option>
                {ROLE_FILTERS.map((role) => (
                  <option key={role} value={role}>
                    {getRoleLabel(role)}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                <ChevronDown size={16} />
              </div>
            </div>
            <button
              aria-label={t('tenant.users.clearFilters')}
              className="p-2 text-slate-400 hover:text-slate-600 border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-surface-dark disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!hasFilters}
              title={t('tenant.users.clearFilters')}
              type="button"
              onClick={clearFilters}
            >
              <Filter size={20} />
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
            <thead className="bg-slate-50 dark:bg-slate-800">
              <tr>
                <th
                  className="px-6 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider w-1/3"
                  scope="col"
                >
                  {t('tenant.users.columns.user')}
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
                  {t('tenant.users.columns.joined')}
                </th>
                <th className="relative px-6 py-3" scope="col">
                  <span className="sr-only">{t('tenant.users.columns.actions')}</span>
                </th>
              </tr>
            </thead>
            <tbody className="bg-surface-light dark:bg-surface-dark divide-y divide-slate-200 dark:divide-slate-700">
              {isLoading ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-slate-500">
                    {t('tenant.users.loading')}
                  </td>
                </tr>
              ) : filteredMembers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-slate-500">
                    {t('tenant.users.noMembers')}
                  </td>
                </tr>
              ) : (
                visibleMembers.map((member) => (
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
                        {getRoleLabel(member.role)}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
                      {formatDateOnly(member.created_at)}
                    </td>
                    <td className="relative px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        aria-expanded={openActionUserId === member.user_id}
                        aria-label={t('tenant.users.openActions', { name: member.name })}
                        className="text-slate-400 hover:text-primary transition-colors"
                        type="button"
                        onClick={() => {
                          setOpenActionUserId((openUserId) =>
                            openUserId === member.user_id ? null : member.user_id
                          );
                        }}
                      >
                        <MoreVertical size={16} />
                      </button>
                      {openActionUserId === member.user_id ? (
                        <div className="absolute right-6 top-10 z-10 w-44 rounded-lg border border-slate-200 bg-white p-1 text-left shadow-lg dark:border-slate-700 dark:bg-slate-900">
                          <button
                            className="w-full rounded-md px-3 py-2 text-left text-sm text-red-600 transition-colors hover:bg-red-50 disabled:cursor-not-allowed disabled:text-slate-400 disabled:hover:bg-transparent dark:text-red-300 dark:hover:bg-red-900/20"
                            disabled={member.role === 'owner' || removingUserId === member.user_id}
                            title={
                              member.role === 'owner' ? t('tenant.users.owner_role_immutable') : ''
                            }
                            type="button"
                            onClick={() => {
                              void handleRemoveMember(member);
                            }}
                          >
                            {removingUserId === member.user_id
                              ? t('tenant.users.saving')
                              : t('tenant.users.actions.remove')}
                          </button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between sm:px-6">
          <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
            <div>
              <p className="text-sm text-slate-700 dark:text-slate-400">
                {t('tenant.users.showingResults', {
                  start: resultStart,
                  end: resultEnd,
                  total: filteredMembers.length,
                })}
              </p>
            </div>
            <div>
              <nav
                aria-label={t('common.pagination.label', { defaultValue: 'Pagination' })}
                className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px"
              >
                <button
                  aria-label={t('common.previous')}
                  className="relative inline-flex items-center px-2 py-2 rounded-l-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-surface-dark text-sm font-medium text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={currentPage === 1}
                  type="button"
                  onClick={() => {
                    setPage((current) => Math.max(current - 1, 1));
                  }}
                >
                  <ChevronLeft size={20} />
                </button>
                <span
                  aria-current="page"
                  className="z-10 bg-primary/10 border-primary text-primary relative inline-flex items-center px-4 py-2 border text-sm font-medium"
                >
                  {currentPage}
                </span>
                <button
                  type="button"
                  aria-label={t('common.next')}
                  className="relative inline-flex items-center px-2 py-2 rounded-r-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-surface-dark text-sm font-medium text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={currentPage >= totalPages}
                  onClick={() => {
                    setPage((current) => Math.min(current + 1, totalPages));
                  }}
                >
                  <ChevronRight size={20} />
                </button>
              </nav>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
