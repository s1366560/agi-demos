import { useI18n } from '../../i18n';
import type { RegisteredUiSlot } from '../../plugins/uiSlotRegistry';
import { SignedUiModuleBoundary } from './SignedUiModuleBoundary';
import type { DesktopRuntimeConfig } from '../../types';

export function PlatformPluginUiSlots({
  slots,
  error,
  loading,
  config,
}: {
  slots: readonly RegisteredUiSlot[];
  error: string | null;
  loading: boolean;
  config: DesktopRuntimeConfig;
}) {
  const { t } = useI18n();
  if (!loading && !error && slots.length === 0) return null;

  return (
    <section className="platform-plugin-ui-slots" aria-live="polite">
      <header>
        <h2>{t('settings.platformPluginUi.title')}</h2>
        <span>
          {loading
            ? t('settings.platformPluginUi.loading')
            : error
              ? t('settings.platformPluginUi.unavailable')
              : t('settings.platformPluginUi.active', { count: slots.length })}
        </span>
      </header>
      {error ? <p>{error}</p> : null}
      {slots.map((slot) => (
        <article key={`${slot.pluginId}:${slot.slot}:${slot.id}`}>
          <strong>{slot.id}</strong>
          <span>{t(`settings.platformPluginUi.slot.${slot.slot}`)}</span>
          <code>{slot.moduleRef}</code>
          {slot.slot === 'tool_result_renderer' && slot.moduleRef.startsWith('signed:') ? (
            <SignedUiModuleBoundary
              config={config}
              pluginId={slot.pluginId}
              expectedDigest={slot.moduleRef.slice('signed:'.length)}
            />
          ) : slot.slot === 'tool_result_renderer' ? (
            <pre aria-label={t('settings.platformPluginUi.rendererPreview')}>
              {JSON.stringify({ contract: 1, kind: 'tool_result', renderer: slot.id }, null, 2)}
            </pre>
          ) : null}
        </article>
      ))}
    </section>
  );
}
