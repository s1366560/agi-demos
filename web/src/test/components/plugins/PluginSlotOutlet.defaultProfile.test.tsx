import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createWebRendererDefinitionsV2, RendererPluginRuntimeV2 } from '@agistack/plugin-runtime';
import { encodeSlotPortMessageV2, type SlotBridgeIdentityV2 } from '@agistack/plugin-slots';

import { PluginSlotOutlet } from '@/components/plugins/PluginSlotOutlet';
import { validateWebRendererContributionsV2 } from '@/routes/v2/webRendererArtifactCatalogV2';
import { projectWebUiSlotAuthorityV2 } from '@/routes/v2/webUiSlotAuthorityProjectionV2';
import { WebUiSlotAuthorityContextV2 } from '@/routes/v2/webUiSlotAuthorityStateV2';

import bootstrapProfile from '../../../../../shared/profiles/memstack-default-bootstrap.v2.json';

const runtimes: RendererPluginRuntimeV2[] = [];

async function defaultAuthority() {
  const runtime = new RendererPluginRuntimeV2(
    'web',
    createWebRendererDefinitionsV2(validateWebRendererContributionsV2)
  );
  runtimes.push(runtime);
  const snapshot = structuredClone(bootstrapProfile);
  const receipt = await runtime.apply({
    schema_version: 2,
    descriptor: {
      profile_id: snapshot.profile_id,
      generation: snapshot.generation,
      digest: snapshot.digest,
    },
    snapshot,
    envelope: {
      version: 1,
      nonce: 'default-slot-regression',
      snapshot_digest: snapshot.digest,
      type_url: 'types.memstack.ai/plugin.profile.v2',
    },
  });
  expect(receipt.status).toBe('ack');
  const generation = runtime.getSnapshot();
  if (!generation) throw new Error('Default renderer generation was not published');
  return projectWebUiSlotAuthorityV2(generation);
}

afterEach(async () => {
  await Promise.all(runtimes.splice(0).map((runtime) => runtime.close()));
  vi.unstubAllGlobals();
});

describe('default profile plugin slot rendering', () => {
  it('does not append duplicate shell controls from default extension artifacts', async () => {
    const authority = await defaultAuthority();
    const { container } = render(
      <WebUiSlotAuthorityContextV2.Provider value={authority}>
        <PluginSlotOutlet
          kind="nav_item"
          context={{ kind: 'navigation', destinations: [{ id: 'billing', label: 'Billing' }] }}
        />
        <PluginSlotOutlet
          kind="settings_page"
          context={{ kind: 'settings', sections: [{ id: 'memory', label: 'Memory' }] }}
        />
        <PluginSlotOutlet
          kind="conversation_renderer"
          context={{
            kind: 'conversation',
            messageCount: 1,
            streaming: false,
            commandsLabel: 'Commands',
          }}
        />
        <PluginSlotOutlet
          kind="composer_action"
          context={{
            kind: 'composer',
            draftRevision: 'r1',
            locked: false,
            templatesLabel: 'Templates',
          }}
        />
        <PluginSlotOutlet
          kind="mcp_canvas"
          context={{
            kind: 'canvas',
            activeTabId: 'document',
            tabs: [{ id: 'document', label: 'Document' }],
          }}
        />
      </WebUiSlotAuthorityContextV2.Provider>
    );

    expect(container.childElementCount).toBe(0);
    expect(authority.status).toBe('ready');
    expect(authority.slotDefinitions.map(({ slot }) => slot).sort()).toEqual([
      'authenticated_shell_surface',
      'tool_result_renderer',
    ]);
  });

  it('keeps the default tool result renderer usable', async () => {
    const authority = await defaultAuthority();
    render(
      <WebUiSlotAuthorityContextV2.Provider value={authority}>
        <PluginSlotOutlet
          kind="tool_result_renderer"
          context={{
            kind: 'tool-result',
            toolName: 'cua_repl',
            status: 'complete',
            presentation: {
              kind: 'repl_output',
              entries: [{ kind: 'text', text: 'Rendered tool output' }],
            },
          }}
        />
      </WebUiSlotAuthorityContextV2.Provider>
    );

    expect(screen.getByText('Rendered tool output')).toBeInTheDocument();
  });

  it.each([
    {
      name: 'navigation',
      kind: 'nav_item' as const,
      context: { kind: 'navigation' as const, destinations: [{ id: 'reports', label: 'Reports' }] },
      action: { type: 'navigate' as const, destinationId: 'reports' },
    },
    {
      name: 'composer',
      kind: 'composer_action' as const,
      context: {
        kind: 'composer' as const,
        draftRevision: 'r1',
        locked: false,
        templatesLabel: 'Templates',
      },
      action: { type: 'composer.open-templates' as const },
    },
  ])('still mounts an explicit $name extension and dispatches its action', async (extension) => {
    const authority = await defaultAuthority();
    const onAction = vi.fn();
    const port = {
      onmessage: null as ((event: MessageEvent) => void) | null,
      postMessage: vi.fn(),
      start: vi.fn(),
      close: vi.fn(),
    };
    vi.stubGlobal(
      'MessageChannel',
      class {
        port1 = port;
        port2 = {};
      }
    );
    const slot = {
      pluginId: 'explicit-extension',
      id: extension.name,
      slot: extension.kind,
      contract: `extension:${extension.name}`,
      moduleRef: `builtin:web-slot-${extension.name}`,
      permission: `ui.${extension.name}`,
      sandbox: true,
    };
    render(
      <WebUiSlotAuthorityContextV2.Provider
        value={{ ...authority, slotDefinitions: [...authority.slotDefinitions, slot] }}
      >
        <PluginSlotOutlet
          kind={extension.kind}
          contractId={slot.contract}
          context={extension.context}
          onAction={onAction}
        />
      </WebUiSlotAuthorityContextV2.Provider>
    );

    const frame = screen.getByTestId(`plugin-slot-${slot.id}`) as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation(() => undefined);
    fireEvent.load(frame);
    const identity = post.mock.calls.at(-1)![0] as SlotBridgeIdentityV2;
    const receive = (payload: Parameters<typeof encodeSlotPortMessageV2>[1]) => {
      act(() =>
        port.onmessage?.(
          new MessageEvent('message', { data: encodeSlotPortMessageV2(identity, payload) })
        )
      );
    };
    receive({ type: 'slot:ready' });
    expect(frame).toHaveAttribute('data-ready', 'true');
    expect(port.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'slot:init', payload: extension.context })
    );
    receive({ type: 'slot:action', action: extension.action });
    expect(onAction).toHaveBeenCalledWith(extension.action);
  });
});
