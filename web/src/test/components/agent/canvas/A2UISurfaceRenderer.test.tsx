import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';

const { viewerSpy, respondToA2UIActionSpy, viewerThrowState } = vi.hoisted(() => ({
  viewerSpy: vi.fn(),
  respondToA2UIActionSpy: vi.fn().mockResolvedValue(undefined),
  viewerThrowState: { enabled: false },
}));

vi.mock('@/components/agent/canvas/MemStackA2UIViewer', () => ({
  MemStackA2UIViewer: (props: unknown) => {
    viewerSpy(props);
    if (viewerThrowState.enabled) {
      throw new Error('mock a2ui viewer failure');
    }
    return null;
  },
}));

vi.mock('@/services/agentService', () => ({
  agentService: {
    respondToA2UIAction: respondToA2UIActionSpy,
  },
}));

import { A2UISurfaceRenderer } from '@/components/agent/canvas/A2UISurfaceRenderer';
import {
  buildA2UIMessageStreamSnapshot,
  type A2UIMessageStreamSnapshot,
} from '@/stores/agent/a2uiMessages';
import { useAgentV3Store } from '@/stores/agentV3';
import { useCanvasStore } from '@/stores/canvasStore';
import {
  getA2UIContractCase,
  getA2UIContractFixtures,
  getA2UIContractMessages,
  getA2UIContractSnapshot,
} from '@/test/fixtures/a2uiContractFixtures';

describe('A2UISurfaceRenderer', () => {
  const components = [
    {
      id: 'root-1',
      component: {
        Text: {
          text: { literalString: 'hello' },
        },
      },
    },
  ];
  const waitingText = 'Waiting for A2UI surface data…';

  beforeEach(() => {
    viewerSpy.mockClear();
    respondToA2UIActionSpy.mockClear();
    viewerThrowState.enabled = false;
    useAgentV3Store.setState({ activeConversationId: null });
    useCanvasStore.setState({ tabs: [], activeTabId: null });
    delete (Object.prototype as Record<string, unknown>).polluted;
  });

  it('renders strict JSONL envelopes', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"s1","components":${JSON.stringify(components)}}}`,
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'root-1',
      components,
    });
  });

  it('renders the shared tier1 canonical contract fixture', () => {
    const messages = getA2UIContractMessages('tier1_interactive_summary');

    render(<A2UISurfaceRenderer surfaceId="summary-surface" messages={messages} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'layout-1',
    });

    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const buttonComponent = props?.components?.find((entry) => entry.id === 'button-1')?.component
      ?.Button as { child?: string; action?: { name?: string } } | undefined;
    expect(buttonComponent).toEqual({
      child: 'button-label-1',
      action: { name: 'view_details' },
    });
  });

  it('renders from a structured snapshot without reparsing the message string', () => {
    const validMessages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"s1","components":${JSON.stringify(components)}}}`,
    ].join('\n');
    const snapshot = buildA2UIMessageStreamSnapshot(validMessages);

    render(<A2UISurfaceRenderer surfaceId="s1" messages="not-json" snapshot={snapshot} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'root-1',
      components,
    });
  });

  it('falls back to parsing messages when the persisted snapshot is malformed', () => {
    const validMessages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"s1","components":${JSON.stringify(components)}}}`,
    ].join('\n');
    const malformedSnapshot = {
      surfaceId: 's1',
      root: 'root-1',
      components: null,
      data: {},
      dataRecords: [],
    } as unknown as A2UIMessageStreamSnapshot;

    render(
      <A2UISurfaceRenderer surfaceId="s1" messages={validMessages} snapshot={malformedSnapshot} />
    );

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'root-1',
      components,
    });
  });

  it('keeps object-shaped component payloads renderable through the snapshot path', () => {
    const objectMessages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      JSON.stringify({
        surfaceUpdate: {
          surfaceId: 's1',
          components: {
            root: {
              id: 'root-1',
              component: {
                Text: {
                  text: { literalString: 'hello' },
                },
              },
            },
          },
        },
      }),
    ].join('\n');
    const snapshot = buildA2UIMessageStreamSnapshot(objectMessages);

    expect(snapshot?.components).toEqual({
      root: expect.objectContaining({ id: 'root-1' }),
    });

    render(<A2UISurfaceRenderer surfaceId="s1" messages="not-json" snapshot={snapshot} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          root?: string;
          components?: Array<{ id: string }>;
        }
      | undefined;
    expect(props?.root).toBe('root-1');
    expect(Array.isArray(props?.components)).toBe(true);
    expect(props?.components?.some((component) => component.id === 'root-1')).toBe(true);
  });

  it('renders the historical snapshot contract fixture through the snapshot path', () => {
    const snapshot = getA2UIContractSnapshot('tier3_historical_snapshot_object_components');

    render(<A2UISurfaceRenderer surfaceId="surface-42" messages="not-json" snapshot={snapshot} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          root?: string;
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    expect(props?.root).toBe('root-1');
    const textComponent = props?.components?.find((entry) => entry.id === 'root-1')?.component
      ?.Text as { text?: { literalString?: string } } | undefined;
    expect(textComponent?.text?.literalString).toBe('Historical hello');
  });

  it('renders accepted+canonicalized typed envelopes through the snapshot replay path', () => {
    const contractCase = getA2UIContractCase('tier2_typed_envelopes');
    const messages = getA2UIContractMessages(contractCase.id);
    const snapshot = buildA2UIMessageStreamSnapshot(messages);

    render(
      <A2UISurfaceRenderer
        surfaceId={contractCase.identity?.surfaceId ?? 'typed-surface'}
        messages="not-json"
        snapshot={snapshot}
      />
    );

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'root-1',
      data: { status: 'ok' },
    });

    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const textComponent = props?.components?.find((entry) => entry.id === 'root-1')?.component
      ?.Text as { text?: { literalString?: string } } | undefined;
    expect(textComponent?.text?.literalString).toBe('Typed hello');
  });

  it('renders the shared Tabs and Modal contract fixture through the canonical message path', () => {
    const contractCase = getA2UIContractCase('tier1_tabs_modal_complete');
    const messages = getA2UIContractMessages(contractCase.id);

    render(
      <A2UISurfaceRenderer
        surfaceId={contractCase.identity?.surfaceId ?? 'references-surface'}
        messages={messages}
      />
    );

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);

    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          root?: string;
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;

    expect(props?.root).toBe('layout-1');

    const tabsComponent = props?.components?.find((entry) => entry.id === 'tabs-1')?.component
      ?.Tabs as
      | {
          tabItems?: Array<{ title?: { literalString?: string }; child?: string }>;
        }
      | undefined;
    expect(tabsComponent?.tabItems).toEqual([
      { title: { literalString: 'Overview' }, child: 'tab-panel-1' },
    ]);

    const modalComponent = props?.components?.find((entry) => entry.id === 'modal-1')?.component
      ?.Modal as { entryPointChild?: string; contentChild?: string } | undefined;
    expect(modalComponent).toEqual({
      entryPointChild: 'modal-trigger-1',
      contentChild: 'modal-body-1',
    });
  });

  it('renders Card payloads with explicit children', () => {
    const cardComponents = [
      {
        id: 'title-1',
        component: {
          Text: {
            text: { literalString: 'Card title' },
          },
        },
      },
      {
        id: 'card-1',
        component: {
          Card: {
            title: 'Card',
            children: { explicitList: ['title-1'] },
          },
        },
      },
    ];
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"card-1"}}',
      `{"surfaceUpdate":{"surfaceId":"s1","components":${JSON.stringify(cardComponents)}}}`,
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          root?: string;
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    expect(props?.root).toBe('card-1');
    const cardComponent = props?.components?.find((entry) => entry.id === 'card-1')?.component
      ?.Card as { children?: { explicitList?: string[] } } | undefined;
    expect(cardComponent?.children?.explicitList).toEqual(['title-1']);
  });

  it('normalizes syntax sugar for Button.label, numeric gap, and Card title components', () => {
    const sugarComponents = [
      {
        id: 'root',
        component: {
          Column: {
            gap: 16,
            children: { explicitList: ['card-1', 'button-1'] },
          },
        },
      },
      {
        id: 'card-1',
        component: {
          Card: {
            title: {
              Text: {
                text: { literal: 'Card title' },
                style: { fontWeight: '700' },
              },
            },
            children: { explicitList: ['body-1'] },
          },
        },
      },
      {
        id: 'body-1',
        component: {
          Text: {
            text: { literalString: 'Body' },
          },
        },
      },
      {
        id: 'button-1',
        component: {
          Button: {
            label: { literalString: 'Submit' },
            action: { name: 'submit' },
          },
        },
      },
    ];
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root"}}',
      `{"surfaceUpdate":{"surfaceId":"s1","components":${JSON.stringify(sugarComponents)}}}`,
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);

    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          root?: string;
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const rootComponent = props?.components?.find((entry) => entry.id === 'root')?.component
      ?.Column as { gap?: string } | undefined;
    const cardComponent = props?.components?.find((entry) => entry.id === 'card-1')?.component
      ?.Card as { title?: unknown; children?: { explicitList?: string[] } } | undefined;
    const titleComponent = props?.components?.find((entry) => entry.id === 'card-1__title')
      ?.component?.Text as
      | { text?: { literalString?: string }; style?: { fontWeight?: string } }
      | undefined;
    const buttonComponent = props?.components?.find((entry) => entry.id === 'button-1')?.component
      ?.Button as { child?: string; label?: unknown } | undefined;
    const buttonLabelComponent = props?.components?.find((entry) => entry.id === 'button-1__label')
      ?.component?.Text as { text?: { literalString?: string } } | undefined;

    expect(rootComponent?.gap).toBe('16px');
    expect(cardComponent?.title).toBeUndefined();
    expect(cardComponent?.children?.explicitList).toEqual(['card-1__title', 'body-1']);
    expect(titleComponent?.text?.literalString).toBe('Card title');
    expect(titleComponent?.style?.fontWeight).toBe('700');
    expect(buttonComponent?.child).toBe('button-1__label');
    expect(buttonComponent?.label).toBeUndefined();
    expect(buttonLabelComponent?.text?.literalString).toBe('Submit');
  });

  it('normalizes phase1 atomic component aliases for the viewer', () => {
    const messages = getA2UIContractMessages('tier2_legacy_aliases');

    render(<A2UISurfaceRenderer surfaceId="form-surface" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;

    const checkboxComponent = props?.components?.find((entry) => entry.id === 'checkbox-1')
      ?.component?.CheckBox as
      | { label?: { literalString?: string }; value?: { literalBoolean?: boolean; path?: string } }
      | undefined;
    expect(checkboxComponent?.label?.literalString).toBe('Email updates');
    expect(checkboxComponent?.value).toEqual({ path: '/form/updates' });

    const selectComponent = props?.components?.find((entry) => entry.id === 'select-1')?.component
      ?.MultipleChoice as
      | {
          description?: { literalString?: string };
          options?: Array<{ label?: { literalString?: string }; value?: string }>;
          selections?: { path?: string };
        }
      | undefined;
    expect(selectComponent?.description?.literalString).toBe('Priority');
    expect(selectComponent?.options).toEqual([{ label: { literalString: 'High' }, value: 'high' }]);
    expect(selectComponent?.selections?.path).toBe('/form/priority');

    const badgeComponent = props?.components?.find((entry) => entry.id === 'badge-1')?.component
      ?.Text as
      | {
          text?: { literalString?: string };
          style?: { borderRadius?: string; backgroundColor?: string };
        }
      | undefined;
    expect(badgeComponent?.text?.literalString).toBe('Active');
    expect(badgeComponent?.style?.borderRadius).toBe('9999px');
    expect(badgeComponent?.style?.backgroundColor).toBe('#e7f7ed');
  });

  it('renders the shared typed-envelope contract fixture', () => {
    const messages = getA2UIContractMessages('tier2_typed_envelopes');

    render(<A2UISurfaceRenderer surfaceId="typed-surface" messages={messages} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);

    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          root?: string;
          data?: Record<string, unknown>;
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    expect(props?.root).toBe('root-1');
    expect(props?.data).toEqual({ status: 'ok' });
    const textComponent = props?.components?.find((entry) => entry.id === 'root-1')?.component
      ?.Text as { text?: { literalString?: string } } | undefined;
    expect(textComponent?.text?.literalString).toBe('Typed hello');
  });

  it('renders the renderer-only List fixture without promoting it into canonical guidance', () => {
    const messages = getA2UIContractMessages('tier3_renderer_only_list_component');
    const fixtures = getA2UIContractFixtures();
    const listFixture = getA2UIContractCase('tier3_renderer_only_list_component');

    render(<A2UISurfaceRenderer surfaceId="list-surface" messages={messages} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(listFixture.canonicalizes_to).toBeNull();
    expect(fixtures.promptGuidance.supportedComponents).not.toContain('List');
    expect(fixtures.promptGuidance.rendererOnlyCompatibility.List).toBe('List');

    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const listComponent = props?.components?.find((entry) => entry.id === 'list-1')?.component;
    expect(listComponent).toEqual({
      List: {
        children: {
          explicitList: [],
        },
      },
    });
  });

  it('normalizes Radio payloads for the custom renderer', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"radio-1"}}',
      JSON.stringify({
        surfaceUpdate: {
          surfaceId: 's1',
          components: [
            {
              id: 'radio-1',
              component: {
                Radio: {
                  label: 'Plan',
                  options: ['Starter', { label: 'Pro', value: 'pro' }],
                  value: { path: '/form/plan', literalString: 'starter' },
                },
              },
            },
          ],
        },
      }),
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const radioComponent = props?.components?.find((entry) => entry.id === 'radio-1')?.component
      ?.Radio as
      | {
          description?: { literalString?: string };
          options?: Array<{ label?: { literalString?: string }; value?: string }>;
          value?: { literalString?: string; path?: string };
        }
      | undefined;
    expect(radioComponent?.description?.literalString).toBe('Plan');
    expect(radioComponent?.options).toEqual([
      { label: { literalString: 'Starter' }, value: 'Starter' },
      { label: { literalString: 'Pro' }, value: 'pro' },
    ]);
    expect(radioComponent?.value).toEqual({ literalString: 'starter', path: '/form/plan' });
  });

  it('preserves combined checkbox default and binding data', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"checkbox-1"}}',
      JSON.stringify({
        surfaceUpdate: {
          surfaceId: 's1',
          components: [
            {
              id: 'checkbox-1',
              component: {
                Checkbox: {
                  label: 'Email updates',
                  value: { literalBoolean: true, path: '/form/updates' },
                },
              },
            },
          ],
        },
      }),
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const checkboxComponent = props?.components?.find((entry) => entry.id === 'checkbox-1')
      ?.component?.CheckBox as { value?: { literalBoolean?: boolean; path?: string } } | undefined;
    expect(checkboxComponent?.value).toEqual({ literalBoolean: true, path: '/form/updates' });
  });

  it('normalizes phase2 container payloads for the viewer', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"layout-1"}}',
      JSON.stringify({
        surfaceUpdate: {
          surfaceId: 's1',
          components: [
            {
              id: 'layout-1',
              component: {
                Column: {
                  children: ['tabs-1', 'modal-1', 'table-1', 'progress-1'],
                },
              },
            },
            {
              id: 'tabs-1',
              component: {
                Tabs: {
                  tabItems: [{ title: 'Overview', child: 'tab-content-1' }],
                },
              },
            },
            {
              id: 'tab-content-1',
              component: {
                Text: {
                  text: { literalString: 'Tab body' },
                },
              },
            },
            {
              id: 'modal-1',
              component: {
                Modal: {
                  entryPointChild: 'modal-trigger-1',
                  contentChild: 'modal-content-1',
                },
              },
            },
            {
              id: 'modal-trigger-1',
              component: {
                Text: {
                  text: { literalString: 'Open' },
                },
              },
            },
            {
              id: 'modal-content-1',
              component: {
                Text: {
                  text: { literalString: 'Modal body' },
                },
              },
            },
            {
              id: 'table-1',
              component: {
                Table: {
                  caption: 'Members',
                  columns: ['Name', { header: 'Status', align: 'center' }],
                  rows: [
                    ['Alice', true],
                    { key: 'row-2', cells: ['Bob', { path: '/members/1/status' }] },
                  ],
                },
              },
            },
            {
              id: 'progress-1',
              component: {
                Progress: {
                  label: 'Completion',
                  value: 42,
                  max: { path: '/progress/max', literalNumber: 100 },
                  tone: 'success',
                },
              },
            },
          ],
        },
      }),
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;

    const tabsComponent = props?.components?.find((entry) => entry.id === 'tabs-1')?.component
      ?.Tabs as
      | {
          tabItems?: Array<{ title?: { literalString?: string }; child?: string }>;
        }
      | undefined;
    expect(tabsComponent?.tabItems).toEqual([
      { title: { literalString: 'Overview' }, child: 'tab-content-1' },
    ]);

    const modalComponent = props?.components?.find((entry) => entry.id === 'modal-1')?.component
      ?.Modal as { entryPointChild?: string; contentChild?: string } | undefined;
    expect(modalComponent).toEqual({
      entryPointChild: 'modal-trigger-1',
      contentChild: 'modal-content-1',
    });

    const tableComponent = props?.components?.find((entry) => entry.id === 'table-1')?.component
      ?.Table as
      | {
          caption?: { literalString?: string };
          columns?: Array<{ header?: { literalString?: string }; align?: string }>;
          rows?: Array<{ key?: string; cells?: Array<Record<string, unknown>> }>;
        }
      | undefined;
    expect(tableComponent?.caption?.literalString).toBe('Members');
    expect(tableComponent?.columns).toEqual([
      { header: { literalString: 'Name' } },
      { header: { literalString: 'Status' }, align: 'center' },
    ]);
    expect(tableComponent?.rows).toEqual([
      {
        key: 'row-0',
        cells: [{ literalString: 'Alice' }, { literalBoolean: true }],
      },
      {
        key: 'row-2',
        cells: [{ literalString: 'Bob' }, { path: '/members/1/status' }],
      },
    ]);

    const progressComponent = props?.components?.find((entry) => entry.id === 'progress-1')
      ?.component?.Progress as
      | {
          label?: { literalString?: string };
          value?: { literalNumber?: number };
          max?: { literalNumber?: number; path?: string };
          tone?: string;
        }
      | undefined;
    expect(progressComponent).toEqual({
      label: { literalString: 'Completion' },
      value: { literalNumber: 42 },
      max: { literalNumber: 100, path: '/progress/max' },
      tone: 'success',
    });
  });

  it('renders fenced multi-line JSON objects', () => {
    const messages = `\`\`\`json
{"beginRendering":{"surfaceId":"s1","root":"root-1"}}
{"surfaceUpdate":{"surfaceId":"s1","components":${JSON.stringify(components)}}}
\`\`\``;

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'root-1',
      components,
    });
  });

  it('renders a JSON array envelope payload', () => {
    const messages = JSON.stringify([
      { beginRendering: { surfaceId: 's1', root: 'root-1' } },
      { surfaceUpdate: { surfaceId: 's1', components } },
    ]);

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'root-1',
      components,
    });
  });

  it('shows a parse error for legacy type-based component payloads', () => {
    const messages = getA2UIContractMessages('invalid_legacy_type_components');

    render(<A2UISurfaceRenderer surfaceId="invalid-surface" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('renders compound envelope payloads after splitting them into canonical records', () => {
    const messages = JSON.stringify({
      beginRendering: { surfaceId: 'server-surface', root: 'root' },
      surfaceUpdate: {
        surfaceId: 'server-surface',
        components: [
          {
            id: 'root',
            component: {
              CheckBox: {
                label: { literalString: 'Enable alerts' },
                value: { literalBoolean: false, path: '/form/enabled' },
              },
            },
          },
        ],
        dataModelUpdate: {
          surfaceId: 'server-surface',
          path: '/',
          contents: [{ form: { enabled: false } }],
        },
      },
    });

    render(<A2UISurfaceRenderer surfaceId="server-surface" messages={messages} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      root: 'root',
      data: { form: { enabled: false } },
    });
  });

  it('renders JSON-like payloads with Python boolean literals', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"server-surface","root":"root"}}',
      '{"surfaceUpdate":{"surfaceId":"server-surface","components":[{"id":"root","component":{"CheckBox":{"label":{"literalString":"Enable alerts"},"value":{"literalBoolean":False,"path":"/form/enabled"}}}}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="server-surface" messages={messages} />);

    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const checkboxPayload = props?.components?.[0]?.component?.CheckBox as
      | { value?: { literalBoolean?: boolean; path?: string } }
      | undefined;
    expect(checkboxPayload?.value).toMatchObject({
      literalBoolean: false,
      path: '/form/enabled',
    });
  });

  it('keeps non-envelope flat payloads invalid even with the broader contract shim', () => {
    const messages = JSON.stringify({
      surfaceId: 'server-surface',
      dataModel: { form: { selected: 'request_env_var' } },
      components: [
        {
          id: 'root',
          component: {
            Column: {
              children: ['title', 'button', 'button-text'],
            },
          },
        },
      ],
    });

    render(<A2UISurfaceRenderer surfaceId="server-surface" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('shows a parse error when the payload surfaceId mismatches the target surface', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"server-surface","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"server-surface","components":${JSON.stringify(components)}}}`,
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="client-tab-id" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('shows a parse error when multiple mismatched surfaceIds are mixed', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s2","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"s2","components":${JSON.stringify(components)}}}`,
      '{"beginRendering":{"surfaceId":"s3","root":"root-2"}}',
      `{"surfaceUpdate":{"surfaceId":"s3","components":${JSON.stringify(components)}}}`,
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('blocks prototype-polluting keys in data updates', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"s1","components":${JSON.stringify(components)}}}`,
      '{"dataModelUpdate":{"surfaceId":"s1","path":"/","contents":[{"safe":"ok"},{"__proto__":{"polluted":"yes"}}]}}',
      '{"dataModelUpdate":{"surfaceId":"s1","path":"/__proto__","contents":[{"polluted":"yes"}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    const props = viewerSpy.mock.calls[0]?.[0] as { data?: Record<string, unknown> } | undefined;
    expect(props?.data).toMatchObject({ safe: 'ok' });
    expect((Object.prototype as Record<string, unknown>).polluted).toBeUndefined();
  });

  it('dispatches actions for the shared interactive identity fixture', async () => {
    const contractCase = getA2UIContractCase('identity_interactive_request');
    const messages = getA2UIContractMessages(contractCase.id);

    useAgentV3Store.setState({ activeConversationId: 'conv-1' });
    useCanvasStore.setState({
      tabs: [
        {
          id: 'a2ui-tab-1',
          title: 'A2UI',
          type: 'a2ui-surface',
          content: '',
          dirty: false,
          createdAt: Date.now(),
          history: [],
          historyIndex: -1,
          a2uiSurfaceId: contractCase.identity?.metadataSurfaceId ?? 'interactive-surface',
          a2uiHitlRequestId: contractCase.identity?.hitlRequestId,
        },
      ],
      activeTabId: 'a2ui-tab-1',
    });

    render(<A2UISurfaceRenderer surfaceId="interactive-surface" messages={messages} />);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          onAction?: (action: {
            actionName: string;
            sourceComponentId: string;
            timestamp: string;
            context: Record<string, unknown>;
          }) => void;
        }
      | undefined;

    await act(async () => {
      props?.onAction?.({
        actionName: 'approve',
        sourceComponentId: 'button-1',
        timestamp: new Date().toISOString(),
        context: { approved: true },
      });
    });

    await waitFor(() => {
      expect(respondToA2UIActionSpy).toHaveBeenCalledWith(
        'a2ui-req-fixture',
        'approve',
        'button-1',
        { approved: true }
      );
    });
  });

  it('does not dispatch actions when the payload surfaceId mismatches the target surface', async () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"server-surface","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"server-surface","components":${JSON.stringify(components)}}}`,
    ].join('\n');

    useAgentV3Store.setState({ activeConversationId: 'conv-1' });
    useCanvasStore.setState({
      tabs: [
        {
          id: 'a2ui-tab-1',
          title: 'A2UI',
          type: 'a2ui-surface',
          content: '',
          dirty: false,
          createdAt: Date.now(),
          history: [],
          historyIndex: -1,
          a2uiSurfaceId: 'server-surface',
          a2uiHitlRequestId: 'hitl-req-1',
        },
      ],
      activeTabId: 'a2ui-tab-1',
    });

    render(<A2UISurfaceRenderer surfaceId="client-tab-id" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
    expect(respondToA2UIActionSpy).not.toHaveBeenCalled();
  });

  it('shows an inline error and skips dispatch when HITL request_id is missing', async () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"server-surface","root":"root-1"}}',
      `{"surfaceUpdate":{"surfaceId":"server-surface","components":${JSON.stringify(components)}}}`,
    ].join('\n');

    useAgentV3Store.setState({ activeConversationId: 'conv-1' });
    useCanvasStore.setState({
      tabs: [
        {
          id: 'a2ui-tab-1',
          title: 'A2UI',
          type: 'a2ui-surface',
          content: '',
          dirty: false,
          createdAt: Date.now(),
          history: [],
          historyIndex: -1,
          a2uiSurfaceId: 'server-surface',
        },
      ],
      activeTabId: 'a2ui-tab-1',
    });

    render(<A2UISurfaceRenderer surfaceId="server-surface" messages={messages} />);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          onAction?: (action: {
            actionName: string;
            sourceComponentId: string;
            timestamp: string;
            context: Record<string, unknown>;
          }) => void;
        }
      | undefined;

    await act(async () => {
      props?.onAction?.({
        actionName: 'approve',
        sourceComponentId: 'btn-1',
        timestamp: new Date().toISOString(),
        context: { ok: true },
      });
    });

    expect(respondToA2UIActionSpy).not.toHaveBeenCalled();
    expect(
      await screen.findByText('This interactive surface is no longer awaiting input.')
    ).toBeInTheDocument();
  });

  it('shows a parse error for malformed surfaceUpdate-only payloads', () => {
    const messages =
      '{"surfaceUpdate":{"components":[{"id":"rev-value","component":{"Text":{"literal":"¥145,230"},"style":{"fontSize":"28px","fontWeight":"bold","color":"#10b981"}}}},{"id":"rev-change","component":{"Text":{"literal":"↑ 15.8%"},"style":{"fontSize":"14px","color":"#10b981"}}}}]}}';

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('shows a parse error for rootless Tabs payloads', () => {
    const messages = JSON.stringify({
      surfaceUpdate: {
        components: [
          {
            id: 'tabs-1',
            component: {
              Tabs: {
                tabItems: [{ title: { literalString: 'Overview' }, child: 'body-1' }],
              },
            },
          },
          {
            id: 'body-1',
            component: {
              Text: {
                text: { literalString: 'Tab body' },
              },
            },
          },
        ],
      },
    });

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('shows a parse error for rootless Modal payloads', () => {
    const messages = JSON.stringify({
      surfaceUpdate: {
        components: [
          {
            id: 'modal-1',
            component: {
              Modal: {
                entryPointChild: 'trigger-1',
                contentChild: 'body-1',
              },
            },
          },
          {
            id: 'trigger-1',
            component: {
              Text: {
                text: { literalString: 'Open' },
              },
            },
          },
          {
            id: 'body-1',
            component: {
              Text: {
                text: { literalString: 'Modal body' },
              },
            },
          },
        ],
      },
    });

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('normalizes Text literal + sibling style component payloads', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"t1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"t1","component":{"Text":{"literal":"hello"},"style":{"color":"#10b981"}}}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const first = props?.components?.[0];
    const textPayload = first?.component?.Text as
      | { text?: { literalString?: string }; style?: { color?: string } }
      | undefined;
    expect(textPayload?.text?.literalString).toBe('hello');
    expect(textPayload?.style?.color).toBe('#10b981');
  });

  it('shows a parse error when beginRendering points at a missing root component', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"missing-root"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"t1","component":{"Text":{"text":{"literal":"hello"}}}},{"id":"t2","component":{"Text":{"text":{"literal":"world"}}}}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('shows a parse error panel when component schema is invalid', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"row-1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"row-1","component":{"Row":{"gap":"8px"}}},{"id":"t1","component":{"Text":{"literal":"hello"}}}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText('Invalid A2UI payload')).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('normalizes legacy TextField value and onChange payloads into text bindings', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"field-1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"field-1","component":{"TextField":{"label":{"literal":"Name"},"value":"Alice","onChange":{"name":"form/name"}}}}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    const props = viewerSpy.mock.calls[0]?.[0] as
      | {
          components?: Array<{ id: string; component: Record<string, unknown> }>;
        }
      | undefined;
    const textFieldPayload = props?.components?.[0]?.component?.TextField as
      | { text?: { path?: string; literalString?: string } }
      | undefined;
    expect(textFieldPayload?.text).toMatchObject({
      path: '/form/name',
      literalString: 'Alice',
    });
  });

  it('supports A2UI valueMap data updates and path-bound string values', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"field-1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"field-1","component":{"TextField":{"label":{"path":"/labels/name"},"text":{"path":"/form/name"}}}}]}}',
      '{"dataModelUpdate":{"surfaceId":"s1","path":"/","contents":[{"key":"labels","valueMap":[{"key":"name","valueString":"Name"}]},{"key":"form","valueMap":[{"key":"name","valueString":"Alice"}]},{"key":"profile","valueMap":[{"key":"nickname"}]},{"key":"items","valueMap":[{"key":"0","valueString":"a"},{"key":"1","valueString":"b"}]},{"key":"rawJson","valueString":"[1,2]"}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.queryByText(waitingText)).not.toBeInTheDocument();
    expect(viewerSpy).toHaveBeenCalledTimes(1);
    expect(viewerSpy.mock.calls[0]?.[0]).toMatchObject({
      data: {
        labels: { name: 'Name' },
        form: { name: 'Alice' },
        profile: { nickname: null },
        items: ['a', 'b'],
        rawJson: '[1,2]',
      },
    });
  });

  it('clears rendered state after deleteSurface', () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
      '{"deleteSurface":{"surfaceId":"s1"}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText(waitingText)).toBeInTheDocument();
    expect(viewerSpy).not.toHaveBeenCalled();
  });

  it('shows text fallback when A2UIViewer throws', () => {
    viewerThrowState.enabled = true;
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"s1","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello fallback"}}}}]}}',
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);
    expect(screen.getByText('hello fallback')).toBeInTheDocument();
    expect(screen.queryByText('A2UI render error')).not.toBeInTheDocument();
  });
});
