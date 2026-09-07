import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ availability: { owner: {} as object, available: true } }));
vi.mock('../../plugins/webOperationAdmissionV2', () => ({
  getWebOperationAvailabilityV2: () => state.availability,
}));
import { useVoiceCallStore } from '../../stores/voiceCallStore';
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
beforeEach(async () => {
  await useVoiceCallStore.getState().reset();
  state.availability = { owner: {}, available: true };
});
afterEach(async () => {
  await useVoiceCallStore.getState().reset();
});
describe('voice call user intent owner', () => {
  it('rejects unavailable starts without restoring a call', async () => {
    state.availability = { owner: {}, available: false };
    await expect(useVoiceCallStore.getState().startCall('c', 'p')).rejects.toThrow('unavailable');
    expect(useVoiceCallStore.getState().status).toBe('idle');
  });
  it('waits for resource drain before returning from endCall', async () => {
    await useVoiceCallStore.getState().startCall('c', 'p');
    const pending = deferred();
    useVoiceCallStore
      .getState()
      .bindCallCleanup(useVoiceCallStore.getState().callId, () => pending.promise);
    let done = false;
    const end = useVoiceCallStore
      .getState()
      .endCall()
      .then(() => {
        done = true;
      });
    expect(useVoiceCallStore.getState().status).toBe('idle');
    await Promise.resolve();
    expect(done).toBe(false);
    pending.resolve();
    await end;
    expect(done).toBe(true);
  });
  it('owner changes during old cleanup never resume the requested new recording', async () => {
    await useVoiceCallStore.getState().startCall('c', 'p');
    const pending = deferred();
    useVoiceCallStore
      .getState()
      .bindCallCleanup(useVoiceCallStore.getState().callId, () => pending.promise);
    const next = useVoiceCallStore.getState().startCall('new', 'p');
    state.availability = { owner: {}, available: true };
    pending.resolve();
    await expect(next).rejects.toMatchObject({ name: 'AbortError' });
    expect(useVoiceCallStore.getState().status).toBe('idle');
  });
  it('old call cleanup cannot retire a newer user-started call', async () => {
    await useVoiceCallStore.getState().startCall('old', 'p');
    const old = useVoiceCallStore.getState().callId;
    const unbind = useVoiceCallStore.getState().bindCallCleanup(old, async () => {});
    await useVoiceCallStore.getState().startCall('new', 'p');
    unbind();
    await useVoiceCallStore.getState().endCall(old);
    await Promise.resolve();
    expect(useVoiceCallStore.getState().conversationId).toBe('new');
  });
  it('effect replay can rebind the same intent but real unmount retires it', async () => {
    await useVoiceCallStore.getState().startCall('c', 'p');
    const id = useVoiceCallStore.getState().callId;
    const first = useVoiceCallStore.getState().bindCallCleanup(id, async () => {});
    first();
    const second = useVoiceCallStore.getState().bindCallCleanup(id, async () => {});
    await Promise.resolve();
    expect(useVoiceCallStore.getState().callId).toBe(id);
    second();
    await Promise.resolve();
    expect(useVoiceCallStore.getState().status).toBe('idle');
  });
});
