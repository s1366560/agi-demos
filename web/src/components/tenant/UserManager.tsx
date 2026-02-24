import React, { useState, useEffect, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

import { Users, UserPlus, Shield, Trash2, Edit3, Search, Mail, Calendar } from 'lucide-react';

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
  role: 'owner' | 'admin' | 'member' | 'viewer';
  created_at: string;
  last_login?: string | undefined;
  is_active: boolean;
}

interface UserManagerProps {
  context: 'tenant' | 'project';
}

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

  const loadTenantUsers = useCallback(async () => {
    if (!currentTenant) return;

    setIsLoading(true);
    setError(null);
    try {
      const response = await tenantService.listMembers(currentTenant.id);
      setUsers(response.users);
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
      const response = await projectService.listMembers(currentProject.id);
      setUsers(response.users);
    } catch (err) {
      console.error('Failed to load project users:', err);
      setError(t('tenant.users.load_error'));
    } finally {
      setIsLoading(false);
    }
  }, [currentProject, t]);

  useEffect(() => {
    if (context === 'tenant' && currentTenant) {
      loadTenantUsers();
    } else if (context === 'project' && currentProject) {
      loadProjectUsers();
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
    if (!window.confirm(t('tenant.users.remove_confirm'))) return;

    try {
      if (context === 'tenant' && currentTenant) {
        await tenantService.removeMember(currentTenant.id, userId);
      } else if (context === 'project' && currentProject) {
        await projectService.removeMember(currentProject.id, userId);
      }

      // Reload users
      if (context === 'tenant') {
        loadTenantUsers();
      } else {
        loadProjectUsers();
      }
    } catch (error) {
      console.error('Failed to remove user:', error);
      alert(t('tenant.users.remove_error'));
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
        loadTenantUsers();
      } else {
        loadProjectUsers();
      }
    } catch (error) {
      console.error('Failed to update user role:', error);
      alert(t('tenant.users.update_error'));
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
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800">
      <div className="p-6 border-b border-gray-200 dark:border-slate-800">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
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
            onClick={handleInviteUser}
            className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors text-sm"
          >
            <UserPlus className="h-4 w-4" />
            <span>{t('tenant.users.inviteMember')}</span>
          </button>
        </div>

        <div className="flex space-x-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400 dark:text-slate-500" />
            <input
              type="text"
              placeholder={t('tenant.users.searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); }}
              className="w-full pl-10 pr-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
            />
          </div>
          <div>
            <select
              value={filterRole}
              onChange={(e) => { setFilterRole(e.target.value); }}
              className="px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            >
              <option value="all">{t('tenant.users.roles.all')}</option>
              <option value="owner">{t('tenant.users.roles.owner')}</option>
              <option value="admin">{t('tenant.users.roles.admin')}</option>
              <option value="member">{t('tenant.users.roles.member')}</option>
              <option value="viewer">{t('tenant.users.roles.viewer')}</option>
            </select>
          </div>
        </div>
      </div>

      <div className="p-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 dark:border-blue-400"></div>
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
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
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
                className="flex items-center justify-between p-4 rounded-lg border border-gray-200 dark:border-slate-700 hover:border-gray-300 dark:hover:border-slate-600 transition-colors"
              >
                <div className="flex items-center space-x-4 flex-1">
                  <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                    <span className="text-white font-medium text-sm">
                      {user.name.charAt(0).toUpperCase()}
                    </span>
                  </div>

                  <div className="flex-1">
                    <div className="flex items-center space-x-2 mb-1">
                      <h4 className="font-medium text-gray-900 dark:text-white">{user.name}</h4>
                      <span
                        className={`px-2 py-1 rounded-full text-xs font-medium ${getRoleColor(user.role)}`}
                      >
                        {user.role}
                      </span>
                      {user.role === 'owner' && (
                        <Shield className="h-4 w-4 text-red-600 dark:text-red-400" />
                      )}
                    </div>
                    <div className="flex items-center space-x-4 text-sm text-gray-500 dark:text-slate-400">
                      <div className="flex items-center space-x-1">
                        <Mail className="h-3 w-3" />
                        <span>{user.email}</span>
                      </div>
                      <div className="flex items-center space-x-1">
                        <Calendar className="h-3 w-3" />
                        <span>加入于 {formatDate(user.created_at)}</span>
                      </div>
                      {user.last_login && (
                        <div className="flex items-center space-x-1">
                          <span>最后登录: {formatDate(user.last_login)}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => { handleEditUser(user); }}
                    className="p-2 text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-md transition-colors"
                    title={t('tenant.users.actions.edit')}
                  >
                    <Edit3 className="h-4 w-4" />
                  </button>
                  {user.role !== 'owner' && (
                    <button
                      onClick={() => handleRemoveUser(user.id)}
                      className="p-2 text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
                      title={t('tenant.users.actions.remove')}
                    >
                      <Trash2 className="h-4 w-4" />
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
                onClick={() => { setIsInviteModalOpen(false); }}
                className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
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
                  onClick={() => { setIsInviteModalOpen(false); }}
                  className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
                >
                  {t('tenant.users.invite_modal.cancel')}
                </button>
                <button
                  type="submit"
                  className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
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
          onClose={() => { setIsEditModalOpen(false); }}
          onSave={handleUpdateRole}
          context={context}
          contextId={context === 'tenant' ? currentTenant?.id || '' : currentProject?.id || ''}
        />
      )}
    </div>
  );
};
