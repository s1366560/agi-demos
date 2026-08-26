import { StrictMode } from 'react';

import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { KasmVNCViewer } from '../../../components/agent/sandbox/KasmVNCViewer';

const rfbMocks = vi.hoisted(() => ({
  close: vi.fn(),
  construct: vi.fn(),
  disconnect: vi.fn(),
}));

vi.mock('@/vendor/kasmvnc/core/rfb.js', () => ({
  default: class MockRFB {
    _rfbConnectionState = '';
    _sock = { close: rfbMocks.close };
    mouseButtonMapper: unknown;
    scaleViewport = false;
    resizeSession = false;
    clipViewport = false;
    background = '';
    qualityLevel = 0;

    constructor(...args: unknown[]) {
      rfbMocks.construct(...args);
    }

    addEventListener = vi.fn();
    sendCredentials = vi.fn();

    disconnect() {
      rfbMocks.disconnect();
    }
  },
}));

vi.mock('@/vendor/kasmvnc/core/mousebuttonmapper.js', () => ({
  default: class MockMouseButtonMapper {
    set = vi.fn();
  },
  XVNC_BUTTONS: {
    LEFT_BUTTON: 1,
    MIDDLE_BUTTON: 2,
    RIGHT_BUTTON: 4,
    BACK_BUTTON: 8,
    FORWARD_BUTTON: 16,
  },
}));

describe('KasmVNCViewer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('creates only one RFB session when mounted in StrictMode', () => {
    render(
      <StrictMode>
        <KasmVNCViewer wsUrl="ws://localhost/desktop" showToolbar={false} />
      </StrictMode>
    );

    expect(rfbMocks.construct).not.toHaveBeenCalled();

    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(rfbMocks.construct).toHaveBeenCalledTimes(1);
  });

  it('does not create an RFB session after unmounting', () => {
    const { unmount } = render(
      <KasmVNCViewer wsUrl="ws://localhost/desktop" showToolbar={false} />
    );

    unmount();
    act(() => {
      vi.runOnlyPendingTimers();
    });

    expect(rfbMocks.construct).not.toHaveBeenCalled();
  });
});
