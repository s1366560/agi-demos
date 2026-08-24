/** Desktop V2 conversation-slot outlet. */

import { usePlatformPluginUiSlots } from '../settings/usePlatformPluginUiSlots';

export function PlatformPluginConversationSlots({
  active,
}: Readonly<{
  active: boolean;
}>) {
  const { slots, error, loading } = usePlatformPluginUiSlots({ active });
  const visible = slots.filter((slot) => slot.slot === 'conversation_renderer');
  if (visible.length === 0) return null;

  return (
    <section
      className="platform-plugin-conversation-slots"
      aria-live="polite"
      data-loading={loading || undefined}
      data-error={error ?? undefined}
    >
      {visible.map((slot) => (
        <div
          key={`${slot.pluginId}:${slot.id}`}
          data-contract={slot.contract}
          data-module-ref={slot.moduleRef}
          data-plugin-id={slot.pluginId}
        />
      ))}
    </section>
  );
}

export default PlatformPluginConversationSlots;
