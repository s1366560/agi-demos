import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Search } from 'lucide-react';

import { AppModal } from '@/components/common';

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

  const handleClose = () => {
    setSearch('');
    onClose();
  };

  const filteredProviders = providers.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <AppModal open={isOpen} onClose={handleClose} title={modalTitle} size="sm">
      {/* Search */}
      <div className="relative mb-3">
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
        />
      </div>

      {/* List */}
      <div className="overflow-y-auto max-h-[50vh] -mx-2 px-2">
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
    </AppModal>
  );
};
