import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Search, X } from 'lucide-react';

import { ProviderConfig } from '../../types/memory';

import { ProviderIcon } from './ProviderIcon';

interface ProviderSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (provider: ProviderConfig) => void;
  providers: ProviderConfig[];
  title?: string | undefined;
}

export const ProviderSelectorModal: React.FC<ProviderSelectorModalProps> = ({
  isOpen,
  onClose,
  onSelect,
  providers,
  title,
}) => {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const modalTitle = title ?? t('components.provider.selector.title');

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const filteredProviders = providers.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="fixed inset-0 bg-slate-950/60" onClick={onClose} />
      <div className="flex min-h-full items-center justify-center p-4">
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="provider-selector-title"
          className="relative flex max-h-[80vh] w-full max-w-md flex-col overflow-hidden rounded-lg bg-white shadow-lg dark:bg-slate-800"
        >
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50 shrink-0">
            <h2
              id="provider-selector-title"
              className="text-lg font-semibold text-slate-900 dark:text-white"
            >
              {modalTitle}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('common.close')}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              <X size={20} />
            </button>
          </div>

          {/* Search */}
          <div className="p-4 border-b border-slate-100 dark:border-slate-800 shrink-0">
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Search size={20} className="text-slate-400" />
              </div>
              <input
                type="text"
                className="block w-full pl-10 pr-4 py-2 border border-slate-300 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder={t('components.provider.selector.searchPlaceholder')}
                aria-label={t('components.provider.selector.searchAria')}
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                }}
                autoFocus
              />
            </div>
          </div>

          {/* List */}
          <div className="overflow-y-auto p-2">
            {filteredProviders.length === 0 ? (
              <div className="p-8 text-center text-slate-500">
                {t('components.provider.selector.empty')}
              </div>
            ) : (
              <div className="space-y-1">
                {filteredProviders.map((provider) => (
                  <button
                    type="button"
                    key={provider.id}
                    onClick={() => {
                      onSelect(provider);
                    }}
                    className="w-full text-left p-3 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700/50 flex items-center gap-3 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-inset group"
                  >
                    <ProviderIcon providerType={provider.provider_type} size="sm" />
                    <div>
                      <div className="text-sm font-medium text-slate-900 dark:text-white group-hover:text-primary transition-colors">
                        {provider.name}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {provider.llm_model}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
