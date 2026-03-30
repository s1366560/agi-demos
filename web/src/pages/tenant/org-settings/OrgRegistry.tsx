/**
 * Organization Registry Page
 *
 * Container registry configuration with CRUD operations and connectivity testing.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { AlertCircle, CheckCircle, Cloud, Pencil, Plus, RefreshCcw, Server, Trash2, Zap, Container, GitMerge, XCircle, Loader2 } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { registryService } from '@/services/registryService';

import {
  useLazyMessage,
  LazyPopconfirm,
  LazySpin,
  LazyModal,
  LazySelect,
} from '@/components/ui/lazyAntd';

/**
 * Registry configuration interface
 */
interface RegistryConfig {
  id: string;
  name: string;
  type: 'docker' | 'gcr' | 'ecr' | 'acr' | 'harbor' | 'custom';
  url: string;
  username?: string;
  password?: string; // Masked
  is_default: boolean;
  status: 'connected' | 'disconnected' | 'error' | 'checking';
  last_checked?: string;
  created_at: string;
}

const REGISTRY_TYPE_OPTIONS = [
  { value: 'docker', label: 'Docker Hub' },
  { value: 'gcr', label: 'Google Container Registry' },
  { value: 'ecr', label: 'AWS ECR' },
  { value: 'acr', label: 'Azure Container Registry' },
  { value: 'harbor', label: 'Harbor' },
  { value: 'custom', label: 'Custom Registry' },
];

const getTypeIcon = (type: string) => {
  switch (type) {
    case 'docker':
      return Container;
    case 'gcr':
    case 'ecr':
      return Cloud;
    case 'ghcr':
      return GitMerge;
    default:
      return Server;
  }
};

const getStatusConfig = (
  status: string
): { color: string; bgColor: string; icon: any; label: string } => {
  switch (status) {
    case 'connected':
      return {
        color: 'text-green-600 dark:text-green-400',
        bgColor: 'bg-green-100 dark:bg-green-900/30',
        icon: CheckCircle,
        label: 'Connected',
      };
    case 'disconnected':
      return {
        color: 'text-slate-600 dark:text-slate-400',
        bgColor: 'bg-slate-100 dark:bg-slate-700',
        icon: XCircle,
        label: 'Disconnected',
      };
    case 'error':
      return {
        color: 'text-red-600 dark:text-red-400',
        bgColor: 'bg-red-100 dark:bg-red-900/30',
        icon: AlertCircle,
        label: 'Error',
      };
    case 'checking':
      return {
        color: 'text-blue-600 dark:text-blue-400',
        bgColor: 'bg-blue-100 dark:bg-blue-900/30',
        icon: Loader2,
        label: 'Checking',
      };
    default:
      return {
        color: 'text-slate-400',
        bgColor: 'bg-slate-100 dark:bg-slate-800',
        icon: AlertCircle,
        label: 'Unknown',
      };
  }
};

interface RegistryFormProps {
  registry?: RegistryConfig | null;
  onSave: (data: Partial<RegistryConfig>) => Promise<void>;
  onCancel: () => void;
  isSubmitting: boolean;
}

const RegistryForm: React.FC<RegistryFormProps> = ({
  registry,
  onSave,
  onCancel,
  isSubmitting,
}) => {
  const { t } = useTranslation();
  const [name, setName] = useState(registry?.name || '');
  const [type, setType] = useState<string>(registry?.type || 'docker');
  const [url, setUrl] = useState(registry?.url || '');
  const [username, setUsername] = useState(registry?.username || '');
  const [password, setPassword] = useState('');
  const [isDefault, setIsDefault] = useState(registry?.is_default || false);

  const handleSubmit = useCallback(async () => {
    const data: Partial<RegistryConfig> = {
      name,
      type: type as RegistryConfig['type'],
      url,
      is_default: isDefault,
    };
    // Only include username if it has a value
    if (username) {
      data.username = username;
    }
    if (password) {
      data.password = password;
    }
    await onSave(data);
  }, [name, type, url, username, password, isDefault, onSave]);

  return (
    <div className="space-y-4">
      <div>
        <label
          htmlFor="registry-name"
          className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
        >
          {t('tenant.orgSettings.registry.form.name')}
        </label>
        <input
          id="registry-name"
          type="text"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
          className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none"
          placeholder={t('tenant.orgSettings.registry.form.namePlaceholder')}
        />
      </div>

      <div>
        <span className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
          {t('tenant.orgSettings.registry.form.type')}
        </span>
        <LazySelect
          value={type}
          onChange={(value: string) => {
            setType(value);
          }}
          options={REGISTRY_TYPE_OPTIONS}
          className="w-full"
        />
      </div>

      <div>
        <label
          htmlFor="registry-url"
          className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
        >
          {t('tenant.orgSettings.registry.form.url')}
        </label>
        <input
          id="registry-url"
          type="text"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
          }}
          className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none font-mono text-sm"
          placeholder={t('tenant.orgSettings.registry.form.urlPlaceholder')}
        />
      </div>

      <div>
        <label
          htmlFor="registry-username"
          className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
        >
          {t('tenant.orgSettings.registry.form.username')}
        </label>
        <input
          id="registry-username"
          type="text"
          value={username}
          onChange={(e) => {
            setUsername(e.target.value);
          }}
          className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none"
          placeholder={t('tenant.orgSettings.registry.form.usernamePlaceholder')}
        />
      </div>

      <div>
        <label
          htmlFor="registry-password"
          className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
        >
          {t('tenant.orgSettings.registry.form.password')}
        </label>
        <input
          id="registry-password"
          type="password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
          }}
          className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none"
          placeholder={
            registry
              ? t('tenant.orgSettings.registry.form.passwordPlaceholderEdit')
              : t('tenant.orgSettings.registry.form.passwordPlaceholder')
          }
        />
        {registry && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            {t('tenant.orgSettings.registry.form.passwordHint')}
          </p>
        )}
      </div>

      <div className="flex items-center gap-2">
        <input
          id="registry-default"
          type="checkbox"
          checked={isDefault}
          onChange={(e) => {
            setIsDefault(e.target.checked);
          }}
          className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary"
        />
        <label htmlFor="registry-default" className="text-sm text-slate-700 dark:text-slate-300">
          {t('tenant.orgSettings.registry.form.setAsDefault')}
        </label>
      </div>

      <div className="flex justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-700">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
        >
          {t('common.cancel')}
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSubmitting || !name || !url}
          className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? t('common.loading') : t('common.save')}
        </button>
      </div>
    </div>
  );
};

export const OrgRegistry: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const currentTenant = useTenantStore((s) => s.currentTenant);

  const [registries, setRegistries] = useState<RegistryConfig[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingRegistry, setEditingRegistry] = useState<RegistryConfig | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [testingRegistryId, setTestingRegistryId] = useState<string | null>(null);

  // Load registries on mount
  useEffect(() => {
    if (!currentTenant?.id) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    const fetchRegistries = async () => {
      setIsLoading(true);
      try {
        const data = await registryService.list(currentTenant.id);
        if (!cancelled) {
          setRegistries(data as unknown as RegistryConfig[]);
        }
      } catch {
        if (!cancelled) {
          message?.error(t('common.error'));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };
    void fetchRegistries();
    return () => {
      cancelled = true;
    };
  }, [currentTenant?.id, message, t]);

  // Stats
  const stats = useMemo(
    () => ({
      total: registries.length,
      connected: registries.filter((r) => r.status === 'connected').length,
      error: registries.filter((r) => r.status === 'error').length,
    }),
    [registries]
  );

  const handleAddRegistry = useCallback(() => {
    setEditingRegistry(null);
    setIsModalOpen(true);
  }, []);

  const handleEditRegistry = useCallback((registry: RegistryConfig) => {
    setEditingRegistry(registry);
    setIsModalOpen(true);
  }, []);

  const handleDeleteRegistry = useCallback(
    async (registry: RegistryConfig) => {
      if (!currentTenant?.id) return;
      try {
        await registryService.remove(currentTenant.id, registry.id);
        setRegistries((prev) => prev.filter((r) => r.id !== registry.id));
        message?.success(t('tenant.orgSettings.registry.deleteSuccess'));
      } catch {
        message?.error(t('common.error'));
      }
    },
    [currentTenant?.id, message, t]
  );

  const handleSaveRegistry = useCallback(
    async (data: Partial<RegistryConfig>) => {
      if (!currentTenant?.id) return;
      setIsSubmitting(true);
      try {
        const request = {
          name: data.name ?? '',
          registry_type: data.type ?? 'docker',
          url: data.url ?? '',
          username: data.username ?? null,
          password: data.password ?? null,
          is_default: data.is_default ?? false,
        };

        if (editingRegistry) {
          // Update existing
          const updated = await registryService.update(
            currentTenant.id,
            editingRegistry.id,
            request
          );
          setRegistries((prev) =>
            prev.map((r) =>
              r.id === editingRegistry.id ? (updated as unknown as RegistryConfig) : r
            )
          );
          message?.success(t('tenant.orgSettings.registry.updateSuccess'));
        } else {
          // Create new
          const created = await registryService.create(currentTenant.id, request);
          setRegistries((prev) => [...prev, created as unknown as RegistryConfig]);
          message?.success(t('tenant.orgSettings.registry.createSuccess'));
        }

        setIsModalOpen(false);
      } catch {
        message?.error(t('common.error'));
      } finally {
        setIsSubmitting(false);
      }
    },
    [currentTenant?.id, editingRegistry, message, t]
  );

  const handleTestConnection = useCallback(
    async (registry: RegistryConfig) => {
      if (!currentTenant?.id) return;
      setTestingRegistryId(registry.id);
      // Update status to checking
      setRegistries((prev) =>
        prev.map((r) => (r.id === registry.id ? { ...r, status: 'checking' as const } : r))
      );

      try {
        const result = await registryService.testConnection(currentTenant.id, registry.id);
        const newStatus = result.success ? 'connected' : 'error';

        setRegistries((prev) =>
          prev.map((r) =>
            r.id === registry.id
              ? {
                  ...r,
                  status: newStatus as RegistryConfig['status'],
                  last_checked: new Date().toISOString(),
                }
              : r
          )
        );

        if (result.success) {
          message?.success(t('tenant.orgSettings.registry.testSuccess'));
        } else {
          message?.error(result.message ?? t('tenant.orgSettings.registry.testFailed'));
        }
      } catch {
        setRegistries((prev) =>
          prev.map((r) => (r.id === registry.id ? { ...r, status: 'error' as const } : r))
        );
        message?.error(t('common.error'));
      } finally {
        setTestingRegistryId(null);
      }
    },
    [currentTenant?.id, message, t]
  );

  if (!currentTenant) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            {t('tenant.orgSettings.registry.title')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.registry.description')}
          </p>
        </div>
        <button
          onClick={handleAddRegistry}
          type="button"
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors text-sm font-medium"
        >
          <Plus size={16} />
          {t('tenant.orgSettings.registry.addRegistry')}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <Server size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{stats.total}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.registry.stats.total')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
              <CheckCircle size={16} className="text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                {stats.connected}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.registry.stats.connected')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-100 dark:bg-red-900/30 rounded-lg">
              <AlertCircle size={16} className="text-red-600 dark:text-red-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-red-600 dark:text-red-400">{stats.error}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.registry.stats.error')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Registries list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LazySpin size="large" />
        </div>
      ) : registries.length === 0 ? (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-12 text-center">
          <Server size={16} className="text-slate-300 dark:text-slate-600 text-5xl" />
          <p className="text-slate-500 dark:text-slate-400 mt-4">
            {t('tenant.orgSettings.registry.noRegistries')}
          </p>
          <button
            onClick={handleAddRegistry}
            type="button"
            className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors text-sm font-medium"
          >
            {t('tenant.orgSettings.registry.addFirstRegistry')}
          </button>
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.registry.colName')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.registry.colType')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.registry.colUrl')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.registry.colStatus')}
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.orgSettings.registry.colLastChecked')}
                </th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('common.actions')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
              {registries.map((registry) => {
                const statusConfig = getStatusConfig(registry.status);
                const isTesting = testingRegistryId === registry.id;

                return (
                  <tr
                    key={registry.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className={`p-1.5 rounded-lg ${statusConfig.bgColor}`}>
                          {(() => { const Icon = getTypeIcon(registry.type); return <Icon size={18} className={`\${statusConfig.color}`} />; })()}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                            {registry.name}
                          </p>
                          {registry.is_default && (
                            <span className="text-xs text-primary-600 dark:text-primary-400">
                              {t('tenant.orgSettings.registry.default')}
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-400 capitalize">
                      {REGISTRY_TYPE_OPTIONS.find((o) => o.value === registry.type)?.label ||
                        registry.type}
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-xs font-mono text-slate-600 dark:text-slate-400 truncate max-w-50">
                        {registry.url}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${statusConfig.bgColor} ${statusConfig.color}`}
                      >
                        {isTesting ? (
                          <RefreshCcw size={14} className="animate-spin" />
                        ) : (
                          <statusConfig.icon size={14} className="mr-1.5" />
                        )}
                        {isTesting ? 'Checking...' : statusConfig.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">
                      {registry.last_checked
                        ? new Date(registry.last_checked).toLocaleString()
                        : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => handleTestConnection(registry)}
                          disabled={isTesting}
                          className="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-md transition-colors disabled:opacity-50"
                        >
                          <Zap size={14} />
                          {t('tenant.orgSettings.registry.testConnection')}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            handleEditRegistry(registry);
                          }}
                          className="inline-flex items-center gap-1 px-2 py-1 text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-md transition-colors"
                        >
                          <Pencil size={14} />
                          {t('common.edit')}
                        </button>
                        <LazyPopconfirm
                          title={t('tenant.orgSettings.registry.deleteConfirm')}
                          onConfirm={() => handleDeleteRegistry(registry)}
                          okText={t('common.confirm')}
                          cancelText={t('common.cancel')}
                        >
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
                          >
                            <Trash2 size={14} />
                            {t('common.delete')}
                          </button>
                        </LazyPopconfirm>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Add/Edit Modal */}
      <LazyModal
        title={
          editingRegistry
            ? t('tenant.orgSettings.registry.editRegistry')
            : t('tenant.orgSettings.registry.addRegistry')
        }
        open={isModalOpen}
        onCancel={() => {
          setIsModalOpen(false);
          setEditingRegistry(null);
        }}
        footer={null}
        width={560}
      >
        <RegistryForm
          registry={editingRegistry}
          onSave={handleSaveRegistry}
          onCancel={() => {
            setIsModalOpen(false);
            setEditingRegistry(null);
          }}
          isSubmitting={isSubmitting}
        />
      </LazyModal>
    </div>
  );
};

export default OrgRegistry;
