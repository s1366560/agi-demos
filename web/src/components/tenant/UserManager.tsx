import React, { useState, useEffect, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import {
  Users,
  UserPlus,
  Shield,
  Trash2,
  Edit3,
  Search,
  Mail,
  Calendar,
  Loader2,
} from 'lucide-react';

import { confirmAction } from '@/utils/confirmAction';
import { formatDateOnly } from '@/utils/date';

import { projectService } from '../../services/projectService';
import { tenantService } from '../../services/tenantService';
import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

import { EditUserModal } from './EditUserModal';

interface User {
  id: string;
  email: string;
  name: string;
  role: 'owner' | 'admin' | 'member' | 'viewer' | 'editor';
  created_at: string;
  last_login?: string | undefined;
  is_active: boolean;
}

interface UserManagerProps {
  context: 'tenant' | 'project';
}

type UserRole = User['role'];

interface UserRecord {
  id?: unknown;
  user_id?: unknown;
  email?: unknown;
  user_email?: unknown;
  name?: unknown;
  user_name?: unknown;
  role?: unknown;
  created_at?: unknown;
  joined_at?: unknown;
  last_login?: unknown;
  is_active?: unknown;
}

type MemberListResponse = UserRecord[] | { users?: UserRecord[]; members?: UserRecord[] };

const userRoles = new Set<UserRole>(['owner', 'admin', 'member', 'viewer', 'editor']);

const readString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value : undefined;

const readRole = (value: unknown): UserRole => {
  const role = readString(value);
  return role && userRoles.has(role as UserRole) ? (role as UserRole) : 'member';
};

const normalizeUserRecord = (record: UserRecord): User | null => {
  const id = readString(record.id) ?? readString(record.user_id);
  if (!id) return null;

  const email = readString(record.email) ?? readString(record.user_email) ?? '';
  const explicitName = readString(record.name) ?? readString(record.user_name);
  const name = explicitName ?? (email || id);
  const createdAt = readString(record.created_at) ?? readString(record.joined_at) ?? '';
  const lastLogin = readString(record.last_login);

  return {
    id,
    email,
    name,
    role: readRole(record.role),
    created_at: createdAt,
    last_login: lastLogin,
    is_active: typeof record.is_active === 'boolean' ? record.is_active : true,
  };
};

const normalizeMemberResponse = (response: MemberListResponse): User[] => {
  const records = Array.isArray(response) ? response : (response.users ?? response.members ?? []);
  return records
    .map((record) => normalizeUserRecord(record))
    .filter((user): user is User => user !== null);
};

export const UserManager: React.FC<UserManagerProps> = ({ context }) => {
  const { t } = useTranslation();
  const { currentTenant } = useTenantStore();
  const { currentProject } = useProjectStore();

  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [_error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterRole, setFilterRole] = useState<string>('all');
  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [removingUserId, setRemovingUserId] = useState<string | null>(null);

  const loadTenantUsers = useCallback(async () => {
    if (!currentTenant) return;

    setIsLoading(true);
    setError(null);
    try {
      const response = (await tenantService.listMembers(currentTenant.id)) as MemberListResponse;
      setUsers(normalizeMemberResponse(response));
    } catch (err) {
      console.error('Failed to load tenant users:', err);
      setError(t('tenant.users.load_error'));
    } finally {
      setIsLoading(false);
    }
  }, [currentTenant, t]);

  const loadProjectUsers = useCallback(async () => {
    if (!currentProject) return;

    setIsLoading(true);
    setError(null);
    try {
      const response = (await projectService.listMembers(currentProject.id)) as MemberListResponse;
      setUsers(normalizeMemberResponse(response));
    } catch (err) {
      console.error('Failed to load project users:', err);
      setError(t('tenant.users.load_error'));
    } finally {
      setIsLoading(false);
    }
  }, [currentProject, t]);

  useEffect(() => {
    if (context === 'tenant' && currentTenant) {
      void loadTenantUsers();
    } else if (context === 'project' && currentProject) {
      void loadProjectUsers();
    }
  }, [context, currentTenant, currentProject, loadTenantUsers, loadProjectUsers]);

  const getRoleColor = (role: string) => {
    switch (role) {
      case 'owner':
        return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300';
      case 'admin':
        return 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300';
      case 'member':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
      case 'viewer':
        return 'bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-300';
      case 'editor':
        return 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-300';
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-300';
    }
  };

  const filteredUsers = users.filter((user) => {
    const matchesSearch =
      user.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      user.email.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesRole = filterRole === 'all' || user.role === filterRole;
    return matchesSearch && matchesRole;
  });

  const handleInviteUser = () => {
    setIsInviteModalOpen(true);
  };

  const handleEditUser = (user: User) => {
    setSelectedUser(user);
    setIsEditModalOpen(true);
  };

  const handleRemoveUser = async (userId: string) => {
    if (!(await confirmAction({ title: t('tenant.users.remove_confirm'), danger: true }))) return;

    setRemovingUserId(userId);
    try {
      if (context === 'tenant' && currentTenant) {
        await tenantService.removeMember(currentTenant.id, userId);
      } else if (context === 'project' && currentProject) {
        await projectService.removeMember(currentProject.id, userId);
      }

      // Reload users
      if (context === 'tenant') {
        void loadTenantUsers();
      } else {
        void loadProjectUsers();
      }
    } catch (error) {
      console.error('Failed to remove user:', error);
      void message.error(t('tenant.users.remove_error'));
    } finally {
      setRemovingUserId(null);
    }
  };

  const handleUpdateRole = async (userId: string, updates: { role: string }) => {
    try {
      if (context === 'tenant' && currentTenant) {
        await tenantService.updateMemberRole(currentTenant.id, userId, updates.role);
      } else if (context === 'project' && currentProject) {
        await projectService.updateMemberRole(currentProject.id, userId, updates.role);
      }

      setIsEditModalOpen(false);
      // Reload users
      if (context === 'tenant') {
        void loadTenantUsers();
      } else {
        void loadProjectUsers();
      }
    } catch (error) {
      console.error('Failed to update user role:', error);
      void message.error(t('tenant.users.update_error'));
    }
  };

  const formatDate = (dateString: string) => {
    return formatDateOnly(dateString);
  };

  if (!currentTenant && context === 'tenant') {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8">
        <div className="text-center">
          <Users className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
            {t('tenant.users.no_workspace_title')}
          </h3>
          <p className="text-gray-600 dark:text-slate-400">{t('tenant.users.no_workspace_desc')}</p>
        </div>
      </div>
    );
  }

  if (!currentProject && context === 'project') {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8">
        <div className="text-center">
          <Users className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
            {t('tenant.users.no_project_title')}
          </h3>
          <p className="text-gray-600 dark:text-slate-400">{t('tenant.users.no_project_desc')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="border-b border-gray-200 p-4 dark:border-slate-800 sm:p-6">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Users className="h-5 w-5 text-gray-600 dark:text-slate-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              {context === 'tenant'
                ? t('tenant.users.workspace_users')
                : t('tenant.users.project_users')}
            </h3>
            <span className="text-sm text-gray-500 dark:text-slate-500">
              {t('tenant.users.users_count', { count: filteredUsers.length })}
            </span>
          </div>
          <button
            type="button"
            onClick={handleInviteUser}
            className="flex w-full items-center justify-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white transition-colors duration-150 hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 sm:w-auto"
          >
            <UserPlus className="h-4 w-4" />
            <span>{t('tenant.users.inviteMember')}</span>
          </button>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400 dark:text-slate-500" />
            <input
              type="text"
              placeholder={t('tenant.users.searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
              }}
              className="w-full pl-10 pr-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
            />
          </div>
          <div>
            <select
              value={filterRole}
              onChange={(e) => {
                setFilterRole(e.target.value);
              }}
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-800 dark:text-white sm:w-auto"
            >
              <option value="all">{t('tenant.users.roles.all')}</option>
              <option value="owner">{t('tenant.users.roles.owner')}</option>
              <option value="admin">{t('tenant.users.roles.admin')}</option>
              <option value="member">{t('tenant.users.roles.member')}</option>
              <option value="editor">{t('tenant.users.roles.editor')}</option>
              <option value="viewer">{t('tenant.users.roles.viewer')}</option>
            </select>
          </div>
        </div>
      </div>

      <div className="p-4 sm:p-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin motion-reduce:animate-none rounded-full h-8 w-8 border-b-2 border-blue-600 dark:border-blue-400"></div>
          </div>
        ) : filteredUsers.length === 0 ? (
          <div className="text-center py-8">
            <Users className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
            <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              {t('tenant.users.empty.title')}
            </h4>
            <p className="text-gray-600 dark:text-slate-400 mb-4">
              {searchTerm || filterRole !== 'all'
                ? t('tenant.users.empty.desc_search')
                : t('tenant.users.empty.desc_invite')}
            </p>
            {!searchTerm && filterRole === 'all' && (
              <button
                onClick={handleInviteUser}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
              >
                {t('tenant.users.empty.invite')}
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {filteredUsers.map((user) => (
              <div
                key={user.id}
                className="flex flex-col gap-4 rounded-lg border border-gray-200 p-4 transition-colors hover:border-gray-300 dark:border-slate-700 dark:hover:border-slate-600 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex min-w-0 flex-1 items-start gap-4 sm:items-center">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600">
                    <span className="text-white font-medium text-sm">
                      {user.name.charAt(0).toUpperCase()}
                    </span>
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <h4 className="break-words font-medium text-gray-900 dark:text-white">
                        {user.name}
                      </h4>
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${getRoleColor(user.role)}`}
                      >
                        {user.role}
                      </span>
                      {user.role === 'owner' && (
                        <Shield className="h-4 w-4 text-red-600 dark:text-red-400" />
                      )}
                    </div>
                    <div className="flex flex-col gap-1 text-sm text-gray-500 dark:text-slate-400 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4">
                      <div className="flex min-w-0 items-center gap-1">
                        <Mail className="h-3 w-3 shrink-0" />
                        <span className="break-all">{user.email}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Calendar className="h-3 w-3 shrink-0" />
                        <span>
                          {t('tenant.users.joinedAt', { date: formatDate(user.created_at) })}
                        </span>
                      </div>
                      {user.last_login && (
                        <div className="flex items-center gap-1">
                          <span>
                            {t('tenant.users.lastLogin', { date: formatDate(user.last_login) })}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 self-end sm:self-center">
                  <button
                    type="button"
                    onClick={() => {
                      handleEditUser(user);
                    }}
                    className="p-2 text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                    title={t('tenant.users.actions.edit')}
                  >
                    <Edit3 className="h-4 w-4" />
                  </button>
                  {user.role !== 'owner' && (
                    <button
                      type="button"
                      onClick={() => {
                        void handleRemoveUser(user.id);
                      }}
                      disabled={removingUserId === user.id}
                      className="p-2 text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-50 disabled:cursor-not-allowed"
                      title={t('tenant.users.actions.remove')}
                    >
                      {removingUserId === user.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Invite User Modal */}
      {isInviteModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-md mx-4">
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
              <div className="flex items-center space-x-2">
                <UserPlus className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  {t('tenant.users.invite_modal.title')}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => {
                  setIsInviteModalOpen(false);
                }}
                aria-label={t('common.close')}
                className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
              >
                <span className="text-xl">×</span>
              </button>
            </div>

            <form className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                  {t('tenant.users.invite_modal.email')} *
                </label>
                <input
                  type="email"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                  placeholder={t('tenant.users.invite_modal.email_placeholder')}
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                  {t('tenant.users.invite_modal.role')} *
                </label>
                <select className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white">
                  <option value="member">{t('tenant.users.roles.member')}</option>
                  <option value="admin">{t('tenant.users.roles.admin')}</option>
                  <option value="viewer">{t('tenant.users.roles.viewer')}</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                  {t('tenant.users.invite_modal.message')}
                </label>
                <textarea
                  className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                  placeholder={t('tenant.users.invite_modal.message_placeholder')}
                  rows={3}
                />
              </div>

              <div className="flex space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => {
                    setIsInviteModalOpen(false);
                  }}
                  className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                >
                  {t('tenant.users.invite_modal.cancel')}
                </button>
                <button
                  type="submit"
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                >
                  {t('tenant.users.invite_modal.submit')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {selectedUser && (
        <EditUserModal
          user={selectedUser}
          isOpen={isEditModalOpen}
          onClose={() => {
            setIsEditModalOpen(false);
          }}
          onSave={(userId, updates) => {
            void handleUpdateRole(userId, updates);
          }}
          context={context}
          contextId={context === 'tenant' ? currentTenant?.id || '' : currentProject?.id || ''}
        />
      )}
    </div>
  );
};
