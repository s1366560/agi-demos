/**
 * ProjectManager State Components
 *
 * Components for displaying loading, empty, and error states.
 */

import { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Folder, AlertCircle, Plus } from 'lucide-react';

import { useProjectManagerContext } from './context';

import type {
  ProjectManagerLoadingProps,
  ProjectManagerEmptyProps,
  ProjectManagerErrorProps,
} from './types';

// ============================================================================
// LOADING STATE
// ============================================================================

export const Loading: FC<ProjectManagerLoadingProps> = ({ message, className = '' }) => {
  return (
    <div
      className={`bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8 ${className}`}
      data-testid="loading-state"
    >
      <div className="flex items-center justify-center">
        <div className="animate-spin motion-reduce:animate-none rounded-full h-8 w-8 border-b-2 border-blue-600 dark:border-blue-400"></div>
        {message && <span className="ml-3 text-gray-600 dark:text-slate-400">{message}</span>}
      </div>
    </div>
  );
};

// ============================================================================
// EMPTY STATE
// ============================================================================

export const Empty: FC<ProjectManagerEmptyProps> = ({
  message: propMessage,
  showCreateButton: propShowCreateButton,
  onCreateClick,
  variant = 'no-projects',
  className = '',
}) => {
  const context = useProjectManagerContext();
  const { t } = useTranslation();

  // Determine message based on variant
  const getMessage = () => {
    if (propMessage) return propMessage;

    switch (variant) {
      case 'no-tenant':
        return t('tenant.projectManager.states.noTenantMessage');
      case 'no-results':
        return t('tenant.projectManager.states.noResultsMessage');
      case 'no-projects':
      default:
        return t('tenant.projectManager.states.noProjectsMessage');
    }
  };

  // Determine subtitle based on variant
  const getSubtitle = () => {
    switch (variant) {
      case 'no-tenant':
        return t('tenant.projectManager.states.noTenantSubtitle');
      case 'no-results':
        return t('tenant.projectManager.states.noResultsSubtitle');
      case 'no-projects':
      default:
        return t('tenant.projectManager.states.noProjectsSubtitle');
    }
  };

  // Determine whether to show create button
  const shouldShowCreateButton =
    propShowCreateButton !== undefined ? propShowCreateButton : variant === 'no-projects';

  // Handle create button click
  const handleCreateClick = () => {
    if (onCreateClick) {
      onCreateClick();
    } else {
      context.setIsCreateModalOpen(true);
    }
  };

  return (
    <div
      className={`bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8 ${className}`}
      data-testid="empty-state"
    >
      <div className="text-center">
        <Folder className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
        <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">{getMessage()}</h3>
        <p className="text-gray-600 dark:text-slate-400 mb-4">{getSubtitle()}</p>
        {shouldShowCreateButton && (
          <button
            type="button"
            onClick={handleCreateClick}
            className="flex items-center space-x-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors mx-auto"
          >
            <Plus className="h-4 w-4" />
            <span>{t('tenant.projectManager.states.createProjectButton')}</span>
          </button>
        )}
      </div>
    </div>
  );
};

// ============================================================================
// ERROR STATE
// ============================================================================

export const Error: FC<ProjectManagerErrorProps> = ({
  error: propError,
  onDismiss,
  className = '',
}) => {
  const context = useProjectManagerContext();

  // Use prop error or context error
  const error = propError !== undefined ? propError : context.error;

  // Handle dismiss
  const handleDismiss = () => {
    if (onDismiss) {
      onDismiss();
    } else {
      context.clearError();
    }
  };

  if (!error) return null;

  return (
    <div
      className={`p-4 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-900/30 ${className}`}
      data-testid="error-state"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
          <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={handleDismiss}
            className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200"
          >
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
};
