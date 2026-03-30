/**
 * Organization Members Page
 *
 * Lists all organization members with invite, role change, and remove capabilities.
 * Includes member search and filter functionality.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input } from 'antd';
import { UserMinus, UserPlus, Users } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazySelect,
  LazyEmpty,
  LazySpin,
  LazyModal,
} from '@/components/ui/lazyAntd';

import type { UserTenant } from '@/types/memory';

const { Search } = Input;

const ROLE_OPTIONS = [
  { value: 'owner', label: 'Owner' },
  { value: 'admin', label: 'Admin' },
  { value: 'editor', label: 'Editor' },
  { value: 'viewer', label: 'Viewer' },
];

const getRoleBadgeColor = (role: string): string => {
  switch (role) {
    case 'owner':
      return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300';
    case 'admin':
      return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
    case 'editor':
      return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
    case 'viewer':
      return 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300';
    default:
      return 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300';
  }
};

export const OrgMembers: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const currentTenant = useTenantStore((s) => s.currentTenant);
  const addMember = useTenantStore((s) => s.addMember);
  const removeMember = useTenantStore((s) => s.removeMember);
  const listMembers = useTenantStore((s) => s.listMembers);
  const isLoading = useTenantStore((s) => s.isLoading);

  const [members, setMembers] = useState<UserTenant[]>([]);
  const [search, setSearch] = useState('');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newMemberEmail, setNewMemberEmail] = useState('');
  const [newMemberRole, setNewMemberRole] = useState('viewer');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [roleFilter, setRoleFilter] = useState('');

  // Load members on mount
  useEffect(() => {
    const loadMembers = async () => {
      if (currentTenant) {
        const result = await listMembers(currentTenant.id);
        setMembers(result);
      }
    };
    loadMembers();
  }, [currentTenant, listMembers]);

  // Filter members by search and role
  const filteredMembers = useMemo(() => {
    let result = members;
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (m) =>
          m.user_id.toLowerCase().includes(q) ||
          (m.user_name && m.user_name.toLowerCase().includes(q)) ||
          (m.user_email && m.user_email.toLowerCase().includes(q))
      );
    }
    if (roleFilter) {
      result = result.filter((m) => m.role === roleFilter);
    }
    return result;
  }, [members, search, roleFilter]);

  // Stats
  const stats = useMemo(
    () => ({
      total: members.length,
      owners: members.filter((m) => m.role === 'owner').length,
      admins: members.filter((m) => m.role === 'admin').length,
      members_count: members.filter((m) => m.role === 'member').length,
      guests: members.filter((m) => m.role === 'guest').length,
    }),
    [members]
  );

  const handleRoleChange = useCallback(
    async (member: UserTenant, newRole: UserTenant['role']) => {
      // Optimistic update
      setMembers((prev) =>
        prev.map((m) => (m.user_id === member.user_id ? { ...m, role: newRole } : m))
      );
      message?.success(t('tenant.orgSettings.members.roleUpdated'));
    },
    [message, t]
  );

  const handleRemove = useCallback(
    async (member: UserTenant) => {
      if (!currentTenant) return;
      try {
        await removeMember(currentTenant.id, member.user_id);
        setMembers((prev) => prev.filter((m) => m.user_id !== member.user_id));
        message?.success(t('tenant.orgSettings.members.removeSuccess'));
      } catch {
        message?.error(t('common.error'));
      }
    },
    [currentTenant, removeMember, message, t]
  );

  const handleAddMember = useCallback(async () => {
    if (!currentTenant || !newMemberEmail) return;
    setIsSubmitting(true);
    try {
      await addMember(currentTenant.id, newMemberEmail, newMemberRole);
      // Refresh members list
      const result = await listMembers(currentTenant.id);
      setMembers(result);
      message?.success(t('tenant.orgSettings.members.inviteSuccess'));
      setIsAddModalOpen(false);
      setNewMemberEmail('');
      setNewMemberRole('viewer');
    } catch {
      message?.error(t('tenant.orgSettings.members.inviteError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [currentTenant, newMemberEmail, newMemberRole, addMember, listMembers, message, t]);

  const getAvatar = (member: UserTenant): string => {
    return (member.user_name ?? member.user_email ?? member.user_id).charAt(0).toUpperCase();
  };

  if (!currentTenant) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            {t('tenant.orgSettings.members.title')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.members.description')}
          </p>
        </div>
        <button
          onClick={() => {
            setIsAddModalOpen(true);
          }}
          type="button"
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors text-sm font-medium"
        >
          <UserPlus size={16} />
          {t('tenant.orgSettings.members.invite')}
        </button>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: t('tenant.orgSettings.members.stats.total'), value: stats.total, icon: Users },
          {
            label: t('tenant.orgSettings.members.stats.owners'),
            value: stats.owners,
            icon: 'workspace_premium',
            color: 'text-purple-600',
          },
          {
            label: t('tenant.orgSettings.members.stats.admins'),
            value: stats.admins,
            icon: 'admin_panel_settings',
            color: 'text-blue-600',
          },
          {
            label: t('tenant.orgSettings.members.stats.members'),
            value: stats.members_count,
            icon: 'person',
            color: 'text-green-600',
          },
          {
            label: t('tenant.orgSettings.members.stats.guests'),
            value: stats.guests,
            icon: 'visibility',
            color: 'text-slate-600',
          },
        ].map((stat) => (
          <div
            key={stat.label}
            className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4"
          >
            <div className="flex items-center gap-3">
              <stat.icon size={20} className={stat.color || ""} />
              <div>
                <p className="text-xl font-bold text-slate-900 dark:text-white">{stat.value}</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">{stat.label}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Search and filter */}
      <div className="flex flex-col sm:flex-row gap-4">
        <Search
          placeholder={t('tenant.orgSettings.members.searchPlaceholder')}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          allowClear
          className="max-w-sm"
        />
        <LazySelect
          value={roleFilter}
          onChange={(val: string) => {
            setRoleFilter(val);
          }}
          options={[
            { value: '', label: t('tenant.orgSettings.members.allRoles') },
            ...ROLE_OPTIONS,
          ]}
          className="w-40"
          placeholder={t('tenant.orgSettings.members.filterByRole')}
        />
      </div>

      {/* Members table */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <LazySpin size="large" />
          </div>
        ) : filteredMembers.length === 0 ? (
          <div className="py-20">
            <LazyEmpty description={t('tenant.orgSettings.members.noMembers')} />
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.members.colUser')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.members.colRole')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.members.colJoined')}
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('common.actions')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {filteredMembers.map((member) => (
                <tr
                  key={member.user_id}
                  className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-full bg-slate-200 dark:bg-slate-600 flex items-center justify-center text-sm font-medium text-slate-600 dark:text-slate-300">
                        {getAvatar(member)}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {member.user_name ?? member.user_id}
                        </p>
                        {member.user_email && (
                          <p className="text-xs text-slate-500 dark:text-slate-400">
                            {member.user_email}
                          </p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {member.role === 'owner' ? (
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getRoleBadgeColor(member.role)}`}
                      >
                        {member.role}
                      </span>
                    ) : (
                      <LazySelect
                        value={member.role}
                        onChange={(val: string) =>
                          handleRoleChange(member, val as UserTenant['role'])
                        }
                        options={ROLE_OPTIONS.filter((r) => r.value !== 'owner')}
                        size="small"
                        className="w-28"
                        disabled={isSubmitting}
                      />
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                    {member.joined_at
                      ? new Date(member.joined_at).toLocaleDateString()
                      : new Date(member.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {member.role !== 'owner' && (
                      <LazyPopconfirm
                        title={t('tenant.orgSettings.members.removeConfirm')}
                        onConfirm={() => handleRemove(member)}
                        okText={t('common.confirm')}
                        cancelText={t('common.cancel')}
                      >
                        <button
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
                          type="button"
                          disabled={isSubmitting}
                        >
                          <UserMinus size={16} />
                          {t('common.remove')}
                        </button>
                      </LazyPopconfirm>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Add Member Modal */}
      <LazyModal
        title={t('tenant.orgSettings.members.inviteMember')}
        open={isAddModalOpen}
        onOk={handleAddMember}
        onCancel={() => {
          setIsAddModalOpen(false);
          setNewMemberEmail('');
          setNewMemberRole('viewer');
        }}
        confirmLoading={isSubmitting}
        okButtonProps={{ disabled: !newMemberEmail }}
      >
        <div className="space-y-4 py-2">
          <div>
            <label
              htmlFor="member-email"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
            >
              {t('tenant.orgSettings.members.email')}
            </label>
            <input
              id="member-email"
              type="email"
              value={newMemberEmail}
              onChange={(e) => {
                setNewMemberEmail(e.target.value);
              }}
              placeholder={t('tenant.orgSettings.members.emailPlaceholder')}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none"
            />
          </div>
          <div>
            <label
              htmlFor="member-role"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
            >
              {t('tenant.orgSettings.members.role')}
            </label>
            <LazySelect
              id="member-role"
              value={newMemberRole}
              onChange={(val: string) => {
                setNewMemberRole(val);
              }}
              options={ROLE_OPTIONS.filter((r) => r.value !== 'owner')}
              className="w-full"
            />
          </div>
        </div>
      </LazyModal>
    </div>
  );
};

export default OrgMembers;
