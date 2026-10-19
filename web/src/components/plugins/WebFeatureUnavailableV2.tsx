import { useTranslation } from 'react-i18next';

export function WebFeatureUnavailableV2() {
  const { t } = useTranslation();
  return (
    <section role="status" className="p-6" data-testid="plugin-feature-unavailable">
      <h2>{t('plugins.featureUnavailable', { defaultValue: 'This feature is unavailable' })}</h2>
      <p>
        {t('plugins.featureUnavailableDescription', {
          defaultValue:
            'The feature is disabled for this workspace. Its configuration can be managed in Plugins.',
        })}
      </p>
    </section>
  );
}
