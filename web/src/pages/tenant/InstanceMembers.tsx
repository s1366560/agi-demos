import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { Input, Table } from 'antd';
import { CheckCircle, Eye, Shield, UserPlus, Users } from 'lucide-react';

import {
  useLazyMessage,
  LazyButton,
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
import type { ColumnsType } from 'antd/es/table';

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
      } catch (err) {
        console.error('Failed to search users:', err);
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

  const columns: ColumnsType<InstanceMemberResponse> = [
    {
      title: t('tenant.instances.members.colUser'),
      key: 'user',
      ellipsis: true,
      render: (_, member) => (
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="shrink-0 w-8 h-8 rounded-full bg-surface-alt dark:bg-surface-elevated flex items-center justify-center text-sm font-medium text-text-secondary dark:text-text-muted-light">
            {(member.user_name ?? member.user_email ?? member.user_id)
              .charAt(0)
              .toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary dark:text-text-inverse truncate">
              {member.user_name ?? member.user_id}
            </p>
            {member.user_email && (
              <p className="text-xs text-text-muted dark:text-text-muted truncate">
                {member.user_email}
              </p>
            )}
          </div>
        </div>
      ),
    },
    {
      title: t('tenant.instances.members.colRole'),
      key: 'role',
      render: (_, member) => (
        <LazySelect
          value={member.role}
          onChange={(val: string) => handleRoleChange(member, val)}
          options={ROLE_OPTIONS}
          size="small"
          className="w-28"
          disabled={isSubmitting}
        />
      ),
    },
    {
      title: t('tenant.instances.members.colJoined'),
      key: 'joined',
      render: (_, member) => new Date(member.created_at).toLocaleDateString(),
    },
    {
      title: t('common.actions'),
      key: 'actions',
      align: 'right',
      render: (_, member) => (
        <LazyPopconfirm
          title={t('tenant.instances.members.removeConfirm')}
          onConfirm={() => handleRemove(member)}
          okText={t('common.confirm')}
          cancelText={t('common.cancel')}
        >
          <LazyButton
            type="link"
            danger
            size="small"
            disabled={isSubmitting}
            className="p-0"
          >
            {t('common.remove')}
          </LazyButton>
        </LazyPopconfirm>
      ),
    },
  ];

  const handleRoleChange = useCallback(
    async (member: InstanceMemberResponse, newRole: string) => {
      if (!instanceId) return;
      try {
        await updateMemberRole(instanceId, member.user_id, { role: newRole });
        message?.success(t('tenant.instances.members.roleUpdated'));
      } catch (err) {
        console.error('Failed to update member role:', err);
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
      } catch (err) {
        console.error('Failed to remove member:', err);
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
    } catch (err) {
      console.error('Failed to add member:', err);
    }
  }, [instanceId, selectedUserId, selectedRole, addMember, message, t]);


  if (!instanceId) return null;

  return (
    <div className="flex flex-col gap-6">
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('tenant.instances.members.title')}
          </h2>
          <p className="text-sm text-text-muted">{t('tenant.instances.members.description')}</p>
        </div>
        <LazyButton
          type="primary"
          icon={<UserPlus size={16} />}
          onClick={() => {
            setIsAddModalOpen(true);
          }}
        >
          {t('tenant.instances.members.addMember')}
        </LazyButton>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-info-bg dark:bg-info-bg-dark rounded-lg">
              <Users size={16} className="text-info-dark dark:text-info-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {members.length}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.members.totalMembers')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-bg dark:bg-purple-bg-dark rounded-lg">
              <Shield size={16} className="text-purple-dark dark:text-purple-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {members.filter((m) => m.role === 'admin').length}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
                {t('tenant.instances.members.admins')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-success-bg dark:bg-success-bg-dark rounded-lg">
              <Eye size={16} className="text-success-dark dark:text-success-light" />
            </div>
            <div>
              <p className="text-2xl font-semibold text-text-primary dark:text-text-inverse">
                {members.filter((m) => m.role === 'viewer').length}
              </p>
              <p className="text-xs text-text-muted dark:text-text-muted">
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
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <LazySpin size="large" />
          </div>
        ) : filteredMembers.length === 0 ? (
          <div className="py-20">
            <LazyEmpty description={t('tenant.instances.members.noMembers')} />
          </div>
        ) : (
          <Table
            columns={columns}
            dataSource={filteredMembers}
            rowKey="id"
            pagination={false}
            className="w-full"
          />
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
              className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
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
              <div className="mt-2 border border-border-light dark:border-border-separator rounded-lg max-h-48 overflow-y-auto">
                {userSearchResults.map((user) => (
                  <LazyButton
                    key={user.id}
                    type="text"
                    block
                    onClick={() => {
                      setSelectedUserId(user.id);
                    }}
                    className={`w-full text-left px-3 py-2 hover:bg-surface-alt dark:hover:bg-surface-elevated flex items-center gap-2 transition-colors h-auto rounded-none border-0 ${
                      selectedUserId === user.id ? 'bg-info-bg dark:bg-info-bg-dark' : ''
                    }`}
                  >
                    <div className="w-7 h-7 rounded-full bg-surface-alt dark:bg-surface-elevated flex items-center justify-center text-xs font-medium">
                      {(user.full_name || user.email).charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 text-left">
                      <p className="text-sm font-medium text-text-primary dark:text-text-inverse">
                        {user.full_name || user.email}
                      </p>
                      <p className="text-xs text-text-muted">{user.email}</p>
                    </div>
                    {selectedUserId === user.id && (
                      <CheckCircle size={16} className="text-info-dark ml-auto" />
                    )}
                  </LazyButton>
                ))}
              </div>
            )}
          </div>
          <div>
            <label
              htmlFor="member-role-select"
              className="block text-sm font-medium text-text-secondary dark:text-text-muted-light mb-1"
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
