import { useI18n } from '../../i18n';
import type { UiSlotDefinition } from '../../plugins/uiSlotRegistry';

export function PlatformPluginUiSlots({
  slots,
  error,
  loading,
}: {
  slots: readonly UiSlotDefinition[];
  error: string | null;
  loading: boolean;
}) {
  const { t } = useI18n();
  if (!loading && !error && slots.length === 0) return null;

  return (
    <details className="platform-plugin-ui-slots" open={error ? true : undefined}>
      <summary>
        <strong>{t('settings.platformPluginUi.title')}</strong>
        <span>
          {loading
            ? t('settings.platformPluginUi.loading')
            : error
              ? t('settings.platformPluginUi.unavailable')
              : t('settings.platformPluginUi.active', { count: slots.length })}
        </span>
      </summary>
      {error ? <p role="alert">{error}</p> : null}
      <div className="platform-plugin-ui-slot-list">
        {slots.map((slot) => (
          <article key={`${slot.pluginId}:${slot.slot}:${slot.id}`}>
            <strong>{slot.id}</strong>
            <span>{t(`settings.platformPluginUi.slot.${slot.slot}`)}</span>
            <code>{slot.moduleRef}</code>
            {slot.slot === 'tool_result_renderer' ? (
              <pre aria-label={t('settings.platformPluginUi.rendererPreview')}>
                {JSON.stringify({ contract: 1, kind: 'tool_result', renderer: slot.id }, null, 2)}
              </pre>
            ) : null}
          </article>
        ))}
      </div>
    </details>
  );
}
