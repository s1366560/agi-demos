import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { UseVoiceChatOptions } from '../../../../hooks/useVoiceChat';
const fixture = vi.hoisted(() => ({
  availability: { owner: {} as object, available: true },
  listeners: new Set<() => void>(),
  options: null as UseVoiceChatOptions | null,
  connect: vi.fn().mockResolvedValue(undefined),
  disconnect: vi.fn().mockResolvedValue(undefined),
  stop: vi.fn().mockResolvedValue(undefined),
  record: vi.fn().mockResolvedValue(undefined),
  enqueue: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('../../../../plugins/webOperationAdmissionV2', () => ({
  getWebOperationAvailabilityV2: () => fixture.availability,
  subscribeWebOperationAvailabilityV2: (listener: () => void) => {
    fixture.listeners.add(listener);
    return () => fixture.listeners.delete(listener);
  },
}));
vi.mock('../../../../hooks/useVoiceChat', () => ({
  useVoiceChat: (options: UseVoiceChatOptions) => {
    fixture.options = options;
    return {
      connect: fixture.connect,
      disconnect: fixture.disconnect,
      startRecording: fixture.record,
      stopRecording: fixture.stop,
      isConnected: false,
      isRecording: false,
      operation: null,
      session: null,
      analyser: null,
    };
  },
}));
vi.mock('../../../../hooks/useAudioQueue', () => ({
  useAudioQueue: () => ({ enqueueChunk: fixture.enqueue, stop: fixture.stop }),
}));
import { VoiceCallPanel } from '../../../../components/agent/chat/VoiceCallPanel';
import { useVoiceCallStore } from '../../../../stores/voiceCallStore';
beforeEach(async () => {
  fixture.availability = { owner: {}, available: true };
  vi.clearAllMocks();
  await useVoiceCallStore.getState().reset();
  await useVoiceCallStore.getState().startCall('conversation', 'project');
});
afterEach(async () => {
  cleanup();
  await useVoiceCallStore.getState().reset();
});
it('rendered panel forwards the exact TTS operation and old callback cannot update a replacement owner', async () => {
  render(<VoiceCallPanel onClose={() => {}} />);
  expect(fixture.connect).toHaveBeenCalledOnce();
  const callbacks = fixture.options!;
  const bytes = new ArrayBuffer(2);
  const operation = { owner: fixture.availability.owner } as never;
  act(() => callbacks.onTtsAudio?.(bytes, operation));
  expect(fixture.enqueue).toHaveBeenCalledWith(bytes, operation);
  await act(async () => {
    fixture.availability = { owner: {}, available: true };
    fixture.listeners.forEach((listener) => listener());
  });
  expect(useVoiceCallStore.getState().status).toBe('idle');
  expect(fixture.disconnect).toHaveBeenCalled();
  act(() => {
    callbacks.onTtsAudio?.(bytes, operation);
    callbacks.onAsrFinal?.('stale');
  });
  expect(fixture.enqueue).toHaveBeenCalledOnce();
  expect(useVoiceCallStore.getState().asrFinalText).toBe('');
  expect(fixture.connect).toHaveBeenCalledOnce();
});
it('unmount immediately closes resources and retires only its own call intent', async () => {
  const view = render(<VoiceCallPanel onClose={() => {}} />);
  view.unmount();
  expect(fixture.disconnect).toHaveBeenCalled();
  expect(fixture.stop).toHaveBeenCalled();
  await act(async () => {});
  expect(useVoiceCallStore.getState().status).toBe('idle');
});
