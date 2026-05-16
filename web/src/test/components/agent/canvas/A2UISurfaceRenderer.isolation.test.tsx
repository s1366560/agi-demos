import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { radioThrowState } = vi.hoisted(() => ({
  radioThrowState: { enabled: true },
}));

vi.mock('@/components/agent/canvas/A2UIRadio', () => ({
  A2UIRadio: () => {
    if (radioThrowState.enabled) {
      throw new Error('mock radio render failure');
    }
    return <div>Recovered radio content</div>;
  },
}));

import { A2UISurfaceRenderer } from '@/components/agent/canvas/A2UISurfaceRenderer';
import { ComponentRegistry } from '@/components/agent/canvas/a2uiInternals';

describe('A2UISurfaceRenderer subtree isolation', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    ComponentRegistry.resetInstance();
    radioThrowState.enabled = true;
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    ComponentRegistry.resetInstance();
  });

  it('isolates a broken tab to the tab panel instead of degrading the whole surface', async () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"tabs-1"}}',
      JSON.stringify({
        surfaceUpdate: {
          surfaceId: 's1',
          components: [
            {
              id: 'tabs-1',
              component: {
                Tabs: {
                  tabItems: [
                    { title: 'Broken', child: 'broken-radio' },
                    { title: 'Healthy', child: 'healthy-text' },
                  ],
                },
              },
            },
            {
              id: 'broken-radio',
              component: {
                Radio: {
                  label: 'Plan repaired',
                  options: ['Starter', 'Pro'],
                  value: 'starter',
                },
              },
            },
            {
              id: 'healthy-text',
              component: {
                Text: {
                  text: { literalString: 'Healthy tab content' },
                },
              },
            },
          ],
        },
      }),
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);

    const brokenTab = await screen.findByRole('tab', { name: 'Broken' });
    expect(brokenTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Healthy' })).toHaveAttribute('aria-selected', 'false');
    expect(await screen.findByText('This tab could not be rendered.')).toBeInTheDocument();
    expect(screen.queryByText('A2UI Text Preview')).not.toBeInTheDocument();

    fireEvent.keyDown(brokenTab, { key: 'ArrowRight' });

    expect(await screen.findByText('Healthy tab content')).toBeInTheDocument();
    expect(screen.queryByText('This tab could not be rendered.')).not.toBeInTheDocument();
    expect(screen.queryByText('A2UI Text Preview')).not.toBeInTheDocument();
  });

  it('keeps sibling list items visible when one child subtree throws', async () => {
    const messages = [
      '{"beginRendering":{"surfaceId":"s1","root":"list-1"}}',
      JSON.stringify({
        surfaceUpdate: {
          surfaceId: 's1',
          components: [
            {
              id: 'list-1',
              component: {
                List: {
                  children: ['good-text', 'broken-radio'],
                },
              },
            },
            {
              id: 'good-text',
              component: {
                Text: {
                  text: { literalString: 'Still good' },
                },
              },
            },
            {
              id: 'broken-radio',
              component: {
                Radio: {
                  label: 'Plan',
                  options: ['Starter', 'Pro'],
                  value: 'starter',
                },
              },
            },
          ],
        },
      }),
    ].join('\n');

    render(<A2UISurfaceRenderer surfaceId="s1" messages={messages} />);

    expect(await screen.findByText('Still good')).toBeInTheDocument();
    expect(await screen.findByText('This list item could not be rendered.')).toBeInTheDocument();
    expect(screen.queryByText('A2UI Text Preview')).not.toBeInTheDocument();
  });

  it('recovers a local fallback after the same node renders successfully again', async () => {
    const baseMessages = [
      '{"beginRendering":{"surfaceId":"s1","root":"layout-1"}}',
      JSON.stringify({
        surfaceUpdate: {
          surfaceId: 's1',
          components: [
            {
              id: 'layout-1',
              component: {
                Column: {
                  children: ['broken-radio'],
                },
              },
            },
            {
              id: 'broken-radio',
              component: {
                Radio: {
                  label: 'Plan',
                  options: ['Starter', 'Pro'],
                  value: 'starter',
                },
              },
            },
          ],
        },
      }),
    ];

    const { rerender } = render(
      <A2UISurfaceRenderer surfaceId="s1" messages={baseMessages.join('\n')} />
    );

    expect(await screen.findByText('This section could not be rendered.')).toBeInTheDocument();

    radioThrowState.enabled = false;
    rerender(
      <A2UISurfaceRenderer
        surfaceId="s1"
        messages={[
          ...baseMessages,
          JSON.stringify({
            surfaceUpdate: {
              surfaceId: 's1',
              components: [
                {
                  id: 'layout-1',
                  component: {
                    Column: {
                      children: ['broken-radio'],
                    },
                  },
                },
                {
                  id: 'broken-radio',
                  component: {
                    Radio: {
                      label: 'Plan repaired',
                      options: ['Starter', 'Pro'],
                      value: 'starter',
                    },
                  },
                },
              ],
            },
          }),
        ].join('\n')}
      />
    );

    expect(await screen.findByText('Recovered radio content')).toBeInTheDocument();
    expect(screen.queryByText('This section could not be rendered.')).not.toBeInTheDocument();
  });
});
