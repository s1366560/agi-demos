import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Input } from 'antd';
import { ArrowLeft, CheckCircle, Eye, Shield, UserMinus, UserPlus, Users } from 'lucide-react';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazySelect,
  LazyEmpty,
  LazySpin,
  LazyModal,
} from '@/components/ui/lazyAntd';

import {
  useInstanceMembers,
  useInstanceLoading,
  useInstanceSubmitting,
  useInstanceError,
  useInstanceActions,
} from '../../stores/instance';

import type { InstanceMemberResponse, UserSearchResult } from '../../services/instanceService';

const { Search } = Input;

const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'editor', label: 'Editor' },
  { value: 'user', label: 'User' },
  { value: 'viewer', label: 'Viewer' },
];

export const InstanceMembers: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const message = useLazyMessage();

  const members = useInstanceMembers();
  const isLoading = useInstanceLoading();
  const isSubmitting = useInstanceSubmitting();
  const error = useInstanceError();
  const { listMembers, addMember, removeMember, updateMemberRole, searchUsers, clearError } =
    useInstanceActions();

  const [search, setSearch] = useState('');
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [userSearchQuery, setUserSearchQuery] = useState('');
  const [userSearchResults, setUserSearchResults] = useState<UserSearchResult[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedRole, setSelectedRole] = useState('user');
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    if (instanceId) {
      listMembers(instanceId);
    }
  }, [instanceId, listMembers]);

  useEffect(() => {
    return () => {
      clearError();
    };
  }, [clearError]);

  useEffect(() => {
    if (error) {
      message?.error(error);
    }
  }, [error, message]);

  // Debounced user search
  useEffect(() => {
    if (!userSearchQuery || userSearchQuery.length < 2 || !instanceId) {
      setUserSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const results = await searchUsers(instanceId, userSearchQuery);
        setUserSearchResults(results);
      } catch {
        // Error handled by store
      } finally {
        setIsSearching(false);
      }
    }, 300);
    return () => {
      clearTimeout(timer);
    };
  }, [userSearchQuery, instanceId, searchUsers]);

  const filteredMembers = useMemo(() => {
    if (!search) return members;
    const q = search.toLowerCase();
    return members.filter(
      (m) =>
        m.user_id.toLowerCase().includes(q) ||
        (m.user_name && m.user_name.toLowerCase().includes(q)) ||
        (m.user_email && m.user_email.toLowerCase().includes(q))
    );
  }, [members, search]);

  const handleRoleChange = useCallback(
    async (member: InstanceMemberResponse, newRole: string) => {
      if (!instanceId) return;
      try {
        await updateMemberRole(instanceId, member.user_id, { role: newRole });
        message?.success(t('tenant.instances.members.roleUpdated'));
      } catch {
        // Error handled by store
      }
    },
    [instanceId, updateMemberRole, message, t]
  );

  const handleRemove = useCallback(
    async (member: InstanceMemberResponse) => {
      if (!instanceId) return;
      try {
        await removeMember(instanceId, member.user_id);
        message?.success(t('tenant.instances.members.removeSuccess'));
      } catch {
        // Error handled by store
      }
    },
    [instanceId, removeMember, message, t]
  );

  const handleAddMember = useCallback(async () => {
    if (!instanceId || !selectedUserId) return;
    try {
      await addMember(instanceId, {
        instance_id: instanceId,
        user_id: selectedUserId,
        role: selectedRole,
      });
      message?.success(t('tenant.instances.members.addSuccess'));
      setIsAddModalOpen(false);
      setSelectedUserId(null);
      setSelectedRole('user');
      setUserSearchQuery('');
      setUserSearchResults([]);
    } catch {
      // Error handled by store
    }
  }, [instanceId, selectedUserId, selectedRole, addMember, message, t]);

  const handleGoBack = useCallback(() => {
    navigate(-1);
  }, [navigate]);

  if (!instanceId) return null;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={handleGoBack}
          type="button"
          className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 mb-3"
        >
          <ArrowLeft size={16} />
          {t('common.back')}
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
              {t('tenant.instances.members.title')}
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t('tenant.instances.members.description')}
            </p>
          </div>
          <button
            onClick={() => {
              setIsAddModalOpen(true);
            }}
            type="button"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
          >
            <UserPlus size={16} />
            {t('tenant.instances.members.addMember')}
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <Users size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {members.length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.members.totalMembers')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
              <Shield size={16} className="text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {members.filter((m) => m.role === 'admin').length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.members.admins')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
              <Eye size={16} className="text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
                {members.filter((m) => m.role === 'viewer').length}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.instances.members.viewers')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Search / Filter */}
      <div className="mb-4">
        <Search
          placeholder={t('tenant.instances.members.searchPlaceholder')}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          allowClear
          className="max-w-sm"
        />
      </div>

      {/* Members Table */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <LazySpin size="large" />
          </div>
        ) : filteredMembers.length === 0 ? (
          <div className="py-20">
            <LazyEmpty description={t('tenant.instances.members.noMembers')} />
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.members.colUser')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.members.colRole')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.instances.members.colJoined')}
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('common.actions')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {filteredMembers.map((member) => {
                return (
                  <tr
                    key={member.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-600 flex items-center justify-center text-sm font-medium text-slate-600 dark:text-slate-300">
                          {(member.user_name ?? member.user_email ?? member.user_id)
                            .charAt(0)
                            .toUpperCase()}
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
                      <LazySelect
                        value={member.role}
                        onChange={(val: string) => handleRoleChange(member, val)}
                        options={ROLE_OPTIONS}
                        size="small"
                        className="w-28"
                        disabled={isSubmitting}
                      />
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                      {new Date(member.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <LazyPopconfirm
                        title={t('tenant.instances.members.removeConfirm')}
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
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Add Member Modal */}
      <LazyModal
        title={t('tenant.instances.members.addMember')}
        open={isAddModalOpen}
        onOk={handleAddMember}
        onCancel={() => {
          setIsAddModalOpen(false);
          setSelectedUserId(null);
          setSelectedRole('user');
          setUserSearchQuery('');
          setUserSearchResults([]);
        }}
        confirmLoading={isSubmitting}
        okButtonProps={{ disabled: !selectedUserId }}
      >
        <div className="space-y-4 py-2">
          <div>
            <label
              htmlFor="user-search-input"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
            >
              {t('tenant.instances.members.searchUser')}
            </label>
            <Search
              id="user-search-input"
              placeholder={t('tenant.instances.members.searchUserPlaceholder')}
              value={userSearchQuery}
              onChange={(e) => {
                setUserSearchQuery(e.target.value);
              }}
              loading={isSearching}
              allowClear
            />
            {userSearchResults.length > 0 && (
              <div className="mt-2 border border-slate-200 dark:border-slate-600 rounded-lg max-h-48 overflow-y-auto">
                {userSearchResults.map((user) => (
                  <button
                    key={user.user_id}
                    type="button"
                    onClick={() => {
                      setSelectedUserId(user.user_id);
                    }}
                    className={`w-full text-left px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-700 flex items-center gap-2 transition-colors ${
                      selectedUserId === user.user_id ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                    }`}
                  >
                    <div className="w-7 h-7 rounded-full bg-slate-200 dark:bg-slate-600 flex items-center justify-center text-xs font-medium">
                      {(user.name || user.email).charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {user.name || user.email}
                      </p>
                      <p className="text-xs text-slate-500">{user.email}</p>
                    </div>
                    {selectedUserId === user.user_id && (
                      <CheckCircle size={16} className="text-blue-600 ml-auto" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label
              htmlFor="member-role-select"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
            >
              {t('tenant.instances.members.colRole')}
            </label>
            <LazySelect
              id="member-role-select"
              value={selectedRole}
              onChange={(val: string) => {
                setSelectedRole(val);
              }}
              options={ROLE_OPTIONS}
              className="w-full"
            />
          </div>
        </div>
      </LazyModal>
    </div>
  );
};
