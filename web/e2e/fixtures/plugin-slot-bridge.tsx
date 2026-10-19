import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { PluginSlotHost } from '../../src/components/plugins/PluginSlotHost';

const slot = {
  pluginId: 'acceptance',
  slot: 'settings_page' as const,
  id: 'settings',
  moduleRef: 'builtin:web-slot-settings',
  permission: 'ui.settings',
  sandbox: true,
};
function Fixture() {
  const [generation, setGeneration] = useState(1);
  const [enabled, setEnabled] = useState(true);
  const [action, setAction] = useState('none');
  const [label, setLabel] = useState('Open graph');
  return (
    <>
      <button onClick={() => setGeneration((value) => value + 1)}>Replace generation</button>
      <button onClick={() => setEnabled(false)}>Disable slot</button>
      <button onClick={() => setLabel('Graph updated')}>Update context</button>
      <output data-testid="action">{action}</output>
      {enabled && (
        <PluginSlotHost
          key={generation}
          slot={slot}
          generationId={`generation-${generation}`}
          initPayload={{
            kind: 'settings',
            tenantId: 'scope-a',
            sections: [{ id: 'graph', label }],
          }}
          onAction={(next) => {
            if (next.type === 'settings.open' && next.sectionId === 'graph')
              setAction(`${generation}:${next.sectionId}`);
          }}
        />
      )}
    </>
  );
}
createRoot(document.getElementById('root')!).render(<Fixture />);
