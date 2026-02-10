import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { X } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

interface User {
  id: string;
  email: string;
  name: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  created_at: string;
  last_login?: string;
  is_active: boolean;
}

interface EditUserModalProps {
  user: User;
  isOpen: boolean;
  onClose: () => void;
  onSave: (userId: string, updates: { role: string }) => void;
  context: 'tenant' | 'project';
  contextId: string;
}

export const EditUserModal: React.FC<EditUserModalProps> = ({
  user,
  isOpen,
  onClose,
  onSave,
  context,
  contextId: _contextId,
}) => {
  const { t } = useTranslation();
  const [role, setRole] = useState(user.role);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setRole(user.role);
  }, [user]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(user.id, { role });
      onClose();
    } catch (error) {
      console.error('Failed to update user role:', error);
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  const availableRoles =
    context === 'tenant'
      ? [
          { value: 'owner', label: t('tenant.users.roles.owner') },
          { value: 'admin', label: t('tenant.users.roles.admin') },
          { value: 'member', label: t('tenant.users.roles.member') },
        ]
      : [
          { value: 'admin', label: t('tenant.users.roles.admin') },
          { value: 'editor', label: t('tenant.users.roles.editor') },
          { value: 'viewer', label: t('tenant.users.roles.viewer') },
        ];

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-md mx-4">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            {t('tenant.users.actions.edit')}
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          {/* User Info */}
          <div className="flex items-center space-x-4 pb-4 border-b border-gray-200 dark:border-slate-800">
            <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
              <span className="text-white font-medium text-lg">
                {user.name.charAt(0).toUpperCase()}
              </span>
            </div>
            <div>
              <h3 className="font-medium text-gray-900 dark:text-white">{user.name}</h3>
              <p className="text-sm text-gray-500 dark:text-slate-400">{user.email}</p>
            </div>
          </div>

          {/* Role Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
              {t('tenant.users.invite_modal.role')}
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as any)}
              disabled={user.role === 'owner' || isSaving}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {availableRoles.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
            {user.role === 'owner' && (
              <p className="mt-1 text-xs text-gray-500 dark:text-slate-500">
                {t('tenant.users.owner_role_immutable')}
              </p>
            )}
          </div>

          {/* User Info */}
          <div className="pt-4 border-t border-gray-200 dark:border-slate-800">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-gray-500 dark:text-slate-500">
                  {t('tenant.users.joined_at_label')}
                </p>
                <p className="text-gray-900 dark:text-white font-medium">
                  {formatDateOnly(user.created_at)}
                </p>
              </div>
              <div>
                <p className="text-gray-500 dark:text-slate-500">
                  {t('tenant.users.last_login_label')}
                </p>
                <p className="text-gray-900 dark:text-white font-medium">
                  {user.last_login
                    ? formatDateOnly(user.last_login)
                    : t('common.time.never')}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex space-x-3 p-6 border-t border-gray-200 dark:border-slate-800">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving || user.role === 'owner'}
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? t('tenant.users.saving') : t('common.save')}
          </button>
        </div>
      </div>
    </div>
  );
};
