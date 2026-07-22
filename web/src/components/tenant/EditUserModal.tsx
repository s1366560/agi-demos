import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { formatDateOnly } from '@/utils/date';

import { AppModal } from '@/components/common';

interface User {
  id: string;
  email: string;
  name: string;
  role: 'owner' | 'admin' | 'member' | 'viewer' | 'editor';
  created_at: string;
  last_login?: string | undefined;
  is_active: boolean;
}

interface EditUserModalProps {
  user: User;
  isOpen: boolean;
  onClose: () => void;
  onSave: (userId: string, updates: { role: string }) => void | Promise<void>;
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
  const [role, setRole] = useState<string>(user.role);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setRole(user.role);
  }, [user]);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      await onSave(user.id, { role });
      onClose();
    } catch (error) {
      console.error('Failed to update user role:', error);
      setSaveError(t('tenant.users.updateRoleFailed', 'Failed to update user role.'));
    } finally {
      setIsSaving(false);
    }
  };

  const availableRoles =
    context === 'tenant'
      ? [
          { value: 'owner', label: t('tenant.users.roles.owner') },
          { value: 'admin', label: t('tenant.users.roles.admin') },
          { value: 'member', label: t('tenant.users.roles.member') },
          { value: 'editor', label: t('tenant.users.roles.editor') },
          { value: 'viewer', label: t('tenant.users.roles.viewer') },
        ]
      : [
          { value: 'admin', label: t('tenant.users.roles.admin') },
          { value: 'member', label: t('tenant.users.roles.member') },
          { value: 'viewer', label: t('tenant.users.roles.viewer') },
        ];

  return (
    <AppModal
      open={isOpen}
      onClose={onClose}
      title={t('tenant.users.actions.edit')}
      size="md"
      isDirty={isSaving}
      closeOnBackdrop={!isSaving}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleSave();
            }}
            disabled={isSaving || user.role === 'owner'}
            className="flex-1 px-4 py-2 bg-primary text-white rounded-md hover:bg-primary/90 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? t('tenant.users.saving') : t('common.save')}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* User Info */}
        <div className="flex items-center space-x-4 pb-4 border-b border-gray-200 dark:border-slate-800">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-900 dark:bg-slate-100">
            <span className="text-lg font-medium text-slate-50 dark:text-slate-900">
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
          <label
            htmlFor="edit-user-role"
            className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2"
          >
            {t('tenant.users.invite_modal.role')}
          </label>
          <select
            id="edit-user-role"
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
            }}
            disabled={user.role === 'owner' || isSaving}
            className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white disabled:opacity-50 disabled:cursor-not-allowed"
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
          {saveError && (
            <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
              {saveError}
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
                {user.last_login ? formatDateOnly(user.last_login) : t('common.time.never')}
              </p>
            </div>
          </div>
        </div>
      </div>
    </AppModal>
  );
};
