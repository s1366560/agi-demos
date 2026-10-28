import { useI18n } from '../../i18n';

type ProviderRequestTimeoutFieldProps = {
  value?: number;
  disabled?: boolean;
  onChange: (milliseconds: number) => void;
};

export function ProviderRequestTimeoutField({
  value = 45_000,
  disabled = false,
  onChange,
}: ProviderRequestTimeoutFieldProps) {
  const { t } = useI18n();
  return (
    <label className="provider-input-label">
      <span>{t('providers.requestTimeout')}</span>
      <input
        type="number"
        min={0.001}
        max={300}
        step={0.001}
        required
        disabled={disabled}
        value={value / 1000}
        onChange={(event) => onChange(Math.round(Number(event.target.value) * 1000))}
      />
      <small>{t('providers.requestTimeoutDescription')}</small>
    </label>
  );
}
