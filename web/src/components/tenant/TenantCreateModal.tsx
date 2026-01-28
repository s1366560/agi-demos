import React, { useState } from 'react';
import { X, Building2, AlertCircle } from 'lucide-react';
import { useTenantStore } from '../../stores/tenant';

interface TenantCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export const TenantCreateModal: React.FC<TenantCreateModalProps> = ({
  isOpen,
  onClose,
  onSuccess
}) => {
  const { createTenant, isLoading, error } = useTenantStore();
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    plan: 'free' as const
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createTenant(formData);
      onSuccess?.();
      onClose();
      setFormData({ name: '', description: '', plan: 'free' });
    } catch (_error) {
      // Error is handled in store
    }
  };

  const handleClose = () => {
    onClose();
    setFormData({ name: '', description: '', plan: 'free' });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-md mx-4">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Building2 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">创建工作空间</h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
            aria-label="关闭创建工作空间弹窗"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="flex items-center space-x-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 rounded-md" role="alert" aria-live="assertive">
              <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" aria-hidden="true" />
              <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
            </div>
          )}

          <div>
            <label htmlFor="tenant-create-name" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              工作空间名称 *
            </label>
            <input
              type="text"
              id="tenant-create-name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
              placeholder="输入工作空间名称"
              required
              disabled={isLoading}
              aria-required="true"
            />
          </div>

          <div>
            <label htmlFor="tenant-create-description" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              描述
            </label>
            <textarea
              id="tenant-create-description"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
              placeholder="描述这个工作空间的用途"
              rows={3}
              disabled={isLoading}
              aria-describedby="tenant-create-description-help"
            />
            <span id="tenant-create-description-help" className="text-xs text-gray-500 dark:text-slate-400">
              可选：描述工作空间的用途
            </span>
          </div>

          <div>
            <label htmlFor="tenant-create-plan" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
              计划类型
            </label>
            <select
              id="tenant-create-plan"
              value={formData.plan}
              onChange={(e) => setFormData({ ...formData, plan: e.target.value as any })}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
              disabled={isLoading}
            >
              <option value="free">免费版</option>
              <option value="basic">基础版</option>
              <option value="premium">高级版</option>
              <option value="enterprise">企业版</option>
            </select>
          </div>

          <div className="flex space-x-3 pt-4">
            <button
              type="button"
              onClick={handleClose}
              className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors"
              disabled={isLoading}
            >
              取消
            </button>
            <button
              type="submit"
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isLoading || !formData.name.trim()}
            >
              {isLoading ? (
                <div className="flex items-center justify-center space-x-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  <span>创建中...</span>
                </div>
              ) : (
                '创建'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
