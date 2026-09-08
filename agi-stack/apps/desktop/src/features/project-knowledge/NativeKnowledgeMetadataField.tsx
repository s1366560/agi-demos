import { useId } from 'react';
import { useI18n } from '../../i18n';

export function NativeKnowledgeMetadataField({
  value,
  onChange,
  readOnly = false,
  invalid = false,
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  invalid?: boolean;
}>) {
  const { t } = useI18n();
  const helpId = useId();
  return (
    <label>
      {t('nativeMemories.metadataLabel')}
      <textarea
        rows={6}
        value={value}
        readOnly={readOnly}
        aria-invalid={invalid || undefined}
        aria-describedby={helpId}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
      />
      <span id={helpId}>{t('nativeMemories.metadataHelp')}</span>
    </label>
  );
}
