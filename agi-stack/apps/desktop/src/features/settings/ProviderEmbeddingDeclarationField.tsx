import { useId } from 'react';
import { useI18n } from '../../i18n';

export function ProviderEmbeddingDeclarationField({
  value,
  models,
  disabled,
  onChange,
}: Readonly<{
  value: string;
  models: readonly string[];
  disabled: boolean;
  onChange: (model: string) => void;
}>) {
  const { t } = useI18n();
  const descriptionId = useId();
  return (
    <div className="provider-embedding-declaration">
      <label>
        <span>{t('providers.embeddingDeclaration')}</span>
        <select
          aria-describedby={descriptionId}
          value={value}
          disabled={disabled}
          onChange={(event) => {
            const selected = event.target.value;
            if (selected === '' || models.includes(selected)) onChange(selected);
          }}
        >
          <option value="">{t('providers.noEmbeddingDeclaration')}</option>
          {models.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </select>
      </label>
      <p id={descriptionId}>{t('providers.embeddingDeclarationHelp')}</p>
    </div>
  );
}
