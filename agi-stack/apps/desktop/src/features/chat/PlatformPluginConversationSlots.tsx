/**
 * Desktop conversation slot surface (I3).
 *
 * Renders `conversation_renderer` plugin slots below the chat timeline,
 * reusing the same reconcile pipeline as the settings surface: signed
 * frontend modules run inside the SignedUiModuleBoundary sandbox (digest
 * verified against the snapshot), builtin rows render nothing here (their
 * renderers are keyed into builtin surfaces elsewhere).
 */

import { usePlatformPluginUiSlots } from '../settings/usePlatformPluginUiSlots';
import { SignedUiModuleBoundary } from '../settings/SignedUiModuleBoundary';
import type { DesktopRuntimeConfig } from '../../types';

export function PlatformPluginConversationSlots({
  active,
  config,
}: Readonly<{
  active: boolean;
  config: DesktopRuntimeConfig;
}>) {
  const { slots, error, loading } = usePlatformPluginUiSlots({ active, config });
  const visible = slots.filter(
    (slot) => slot.slot === 'conversation_renderer' && slot.moduleRef.startsWith('signed:')
  );
  if (visible.length === 0) return null;

  return (
    <section
      className="platform-plugin-conversation-slots"
      aria-live="polite"
      data-loading={loading || undefined}
      data-error={error ?? undefined}
    >
      {visible.map((slot) => (
        <SignedUiModuleBoundary
          key={`${slot.pluginId}:${slot.id}`}
          config={config}
          pluginId={slot.pluginId}
          expectedDigest={slot.moduleRef.slice('signed:'.length)}
        />
      ))}
    </section>
  );
}

export default PlatformPluginConversationSlots;
