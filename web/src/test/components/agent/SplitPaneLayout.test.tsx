import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SplitPaneLayout } from '@/components/agent/SplitPaneLayout';

describe('SplitPaneLayout', () => {
  const renderLayout = (onSplitRatioChange = vi.fn()) => {
    render(
      <div style={{ height: 600, width: 900 }}>
        <SplitPaneLayout
          leftContent={<div data-testid="left-content">Conversation</div>}
          rightContent={<div data-testid="right-content">Workspace</div>}
          splitRatio={0.4}
          onSplitRatioChange={onSplitRatioChange}
          leftMinWidth="280px"
          rightMinWidth="320px"
          statusBar={<div data-testid="status-bar">Ready</div>}
        />
      </div>
    );
  };

  it('keeps pane min widths in CSS variables so mobile CSS can override them', () => {
    renderLayout();

    const leftPane = screen.getByTestId('left-content').parentElement;
    const rightPane = screen.getByTestId('right-content').parentElement;

    expect(leftPane).toHaveClass('split-pane-panel');
    expect(rightPane).toHaveClass('split-pane-panel', 'split-pane-right');
    expect(leftPane).toHaveStyle({ width: '40%' });
    expect(rightPane).toHaveStyle({ width: '60%' });
    expect(leftPane?.style.minWidth).toBe('');
    expect(rightPane?.style.minWidth).toBe('');
    expect(leftPane?.style.getPropertyValue('--split-pane-min-width')).toBe('280px');
    expect(rightPane?.style.getPropertyValue('--split-pane-min-width')).toBe('320px');
  });

  it('captures a pointer until the resize ends across an embedded pane', () => {
    const change = vi.fn();
    renderLayout(change);
    const handle = screen.getByRole('slider');
    const capture = vi.fn();
    Object.defineProperty(handle, 'setPointerCapture', { value: capture });
    Object.defineProperty(handle.parentElement, 'offsetWidth', { value: 1000 });
    const pointer = (type: string, x: number) => {
      const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x });
      Object.defineProperty(event, 'pointerId', { value: 3 });
      fireEvent(handle, event);
    };
    pointer('pointerdown', 400);
    expect(capture).toHaveBeenCalledWith(3);
    pointer('pointermove', 500);
    expect(change).toHaveBeenLastCalledWith(0.5);
    pointer('lostpointercapture', 500);
    pointer('pointermove', 600);
    expect(change).toHaveBeenCalledTimes(1);
  });

  it('preserves keyboard resizing behavior on the drag handle', () => {
    const onSplitRatioChange = vi.fn();
    renderLayout(onSplitRatioChange);

    fireEvent.keyDown(screen.getByRole('slider', { name: 'Resize panels' }), {
      key: 'ArrowRight',
    });

    expect(onSplitRatioChange).toHaveBeenCalledTimes(1);
    expect(onSplitRatioChange.mock.calls[0]?.[0]).toBeCloseTo(0.42);
  });
});
