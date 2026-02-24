import React, { useState } from 'react';


import { ProviderConfig } from '../../types/memory';
import { MaterialIcon } from '../agent/shared/MaterialIcon';

import { ProviderIcon } from './ProviderIcon';

interface ProviderSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (provider: ProviderConfig) => void;
  providers: ProviderConfig[];
  title?: string;
}

export const ProviderSelectorModal: React.FC<ProviderSelectorModalProps> = ({
  isOpen,
  onClose,
  onSelect,
  providers,
  title = 'Select Provider',
}) => {
  const [search, setSearch] = useState('');

  if (!isOpen) return null;

  const filteredProviders = providers.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative w-full max-w-md bg-white dark:bg-slate-800 rounded-2xl shadow-xl overflow-hidden flex flex-col max-h-[80vh]">
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50 shrink-0">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{title}</h2>
            <button
              onClick={onClose}
              className="p-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            >
              <MaterialIcon name="close" size={20} />
            </button>
          </div>

          {/* Search */}
          <div className="p-4 border-b border-slate-100 dark:border-slate-800 shrink-0">
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <MaterialIcon name="search" size={20} className="text-slate-400" />
              </div>
              <input
                type="text"
                className="block w-full pl-10 pr-4 py-2 border border-slate-300 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder="Search providers..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); }}
                autoFocus
              />
            </div>
          </div>

          {/* List */}
          <div className="overflow-y-auto p-2">
            {filteredProviders.length === 0 ? (
              <div className="p-8 text-center text-slate-500">No providers found.</div>
            ) : (
              <div className="space-y-1">
                {filteredProviders.map((provider) => (
                  <button
                    key={provider.id}
                    onClick={() => { onSelect(provider); }}
                    className="w-full text-left p-3 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700/50 flex items-center gap-3 transition-colors group"
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
