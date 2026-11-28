import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPageVoiceAuthority } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/pageVoiceAuthority';
import { runPageVoice, type VoiceSocket } from '../../../../agi-stack/packages/plugin-slots/src/pageVoice';

function socket(): VoiceSocket {
  return { binaryType: '', readyState: 0, onopen: null, onclose: null, onerror: null, onmessage: null,
    close: vi.fn(), send: vi.fn() };
}

describe('trusted microphone sessions', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
  it('does not open a socket without trusted approval, or for a foreign conversation', async () => {
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
    const accepted = { conversation_id: 'owned', principal_id: 'owner', ticket:'fixture-ticket' };
    const open = vi.fn(async () => socket());
    const authorize = vi.fn(async () => accepted);
    const voice = createPageVoiceAuthority({ tenantId:'t', projectId:'p', pluginId:'pkg', locale:'en', open, authorize });
    await expect(voice.start('dictation','foreign',new AbortController().signal, vi.fn())).rejects.toThrow('voice_scope_invalid');
    const voiceRequest = voice.start('voice','owned',new AbortController().signal, vi.fn());
    await vi.waitFor(() => expect(document.querySelector('dialog')).not.toBeNull());
    expect(document.querySelector('dialog')?.textContent).toContain('owned');
    expect(open).not.toHaveBeenCalled();
    document.querySelector<HTMLButtonElement>('dialog button')!.click();
    await expect(voiceRequest).rejects.toThrow('microphone_permission_denied');
    expect(open).not.toHaveBeenCalled();
  });

  it('stops a granted call if the authenticated principal changes and invalidates its handle', async () => {
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
    vi.useFakeTimers();
    const active = socket();
    let principal = 'first';
    const authorize = vi.fn(async () => ({ conversation_id: 'owned', principal_id: principal, ticket:'fixture-ticket' }));
    const voice = createPageVoiceAuthority({ tenantId:'t', projectId:'p', pluginId:'pkg', locale:'en',
      open: async () => active, authorize });
    const events = vi.fn();
    const request = voice.start('voice','owned',new AbortController().signal, events);
    const rejected = expect(request).rejects.toThrow('voice_grant_revoked');
    await vi.advanceTimersByTimeAsync(0);
    document.querySelectorAll<HTMLButtonElement>('dialog button')[1]!.click();
    await vi.advanceTimersByTimeAsync(0);
    const {id} = events.mock.calls[0]![0] as {id:string};
    voice.mute(id, true);
    principal = 'different';
    await vi.advanceTimersByTimeAsync(3000);
    await rejected;
    expect(active.close).toHaveBeenCalledOnce();
    expect(() => voice.mute(id, false)).toThrow('voice_session_unavailable');
  });

  it('stops tracks delivered after abort and discards late transcripts', async () => {
    let deliver!: (media: unknown) => void;
    const getUserMedia = vi.fn(() => new Promise(resolve => {deliver=resolve;}));
    vi.stubGlobal('navigator', {mediaDevices:{getUserMedia}});
    const active = socket();
    active.readyState = 1;
    const controller = new AbortController();
    const events = vi.fn();
    const request = runPageVoice({socket: active, ticket:'fixture-ticket', mode:'dictation', signal:controller.signal, workletUrl:'worklet.js', event:events, bindMute:vi.fn()});
    const late = active.onmessage;
    controller.abort();
    await request;
    const stop = vi.fn();
    deliver({getTracks: () => [{stop}]});
    await Promise.resolve();
    late?.({data:'{"type":"asr_final","text":"old"}'});
    expect(stop).toHaveBeenCalledOnce();
    expect(active.close).toHaveBeenCalledOnce();
    expect(events).not.toHaveBeenCalled();
  });
});
