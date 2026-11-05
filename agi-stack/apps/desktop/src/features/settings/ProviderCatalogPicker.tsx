import { useState } from 'react';
import { CubeIcon, MagnifyingGlassIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { LlmProviderCatalogModel } from '../../types';

type ProviderCatalogPickerProps = {
  models: readonly LlmProviderCatalogModel[];
  selectedModels: ReadonlySet<string>;
  primaryModel: string;
  onToggle: (id: string) => void;
};

export function ProviderCatalogPicker({
  models,
  selectedModels,
  primaryModel,
  onToggle,
}: ProviderCatalogPickerProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const filter = query.trim().toLowerCase();
  const visibleModels = models.filter((model) => model.id.toLowerCase().includes(filter));

  return (
    <>
      <div className="provider-model-tools">
        <label>
          <MagnifyingGlassIcon />
          <input
            type="search"
            aria-label={t('providers.searchModelIds')}
            placeholder={t('providers.searchModelIds')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>
      <div className="provider-wizard-models">
        {visibleModels.map((model) => (
          <label key={model.id}>
            <input
              type="checkbox"
              checked={selectedModels.has(model.id)}
              disabled={model.id === primaryModel}
              onChange={() => onToggle(model.id)}
            />
            <CubeIcon />
            <span>
              <b>{model.id}</b>
              <small>{t(`providers.capability.${model.capability}`)}</small>
            </span>
          </label>
        ))}
        {visibleModels.length === 0 ? <p role="status">{t('settings.noMatches')}</p> : null}
      </div>
    </>
  );
}
