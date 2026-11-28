import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import type { VoiceCallRuntime } from '../features/chat/voiceCallRuntime';
import type { VoiceTranscriptionRuntime } from '../features/chat/voiceTranscriptionRuntime';
import {
  prepareVoiceSessionV2,
  requireVoiceSessionRuntimeV2,
  voiceSessionErrorV2,
  type PreparedVoiceSessionV2,
  type RetainedVoiceSessionV2,
  type VoiceSessionInputV2,
  type VoiceSessionRuntimeV2,
} from './desktopVoiceSessionContractV2';
import { createVoiceSessionRuntimeProjectionV2 } from './desktopVoiceSessionRuntimeProjectionV2';
import { retainVoiceSessionRuntimeV2 } from './desktopVoiceSessionRetainedRuntimeV2';
export type { VoiceSessionInputV2, RetainedVoiceSessionV2 } from './desktopVoiceSessionContractV2';
export const DESKTOP_VOICE_SESSION_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/voice-session-authority';
export const DESKTOP_VOICE_SESSION_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.voice-session-authority';
export const DESKTOP_VOICE_SESSION_AUTHORITY_VERSION_V2 = '1.0.0';
export interface DesktopVoiceSessionOperationsV2 {
  acquireTranscription(
    input: VoiceSessionInputV2,
  ): Promise<RetainedVoiceSessionV2<VoiceTranscriptionRuntime>>;
  acquireCall(input: VoiceSessionInputV2): Promise<RetainedVoiceSessionV2<VoiceCallRuntime>>;
}
export interface DesktopVoiceSessionAuthorityServiceV2 {
  createRuntime(
    input: PreparedVoiceSessionV2,
    kind: 'transcription' | 'call',
  ): VoiceSessionRuntimeV2;
}
export function applyDesktopVoiceSessionAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'retained-voice-session' || Object.keys(config).length !== 1)
    throw voiceSessionErrorV2('config_invalid');
  context.provide(
    DESKTOP_VOICE_SESSION_AUTHORITY_SERVICE_V2,
    Object.freeze({ createRuntime: createVoiceSessionRuntimeProjectionV2 }),
  );
}
export const desktopVoiceSessionAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_VOICE_SESSION_AUTHORITY_MODULE_REF_V2,
  contractDigest: generatedDigestV2(),
  apply: applyDesktopVoiceSessionAuthorityV2,
});
export function createDesktopVoiceSessionOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopVoiceSessionOperationsV2 {
  async function acquire<T extends VoiceSessionRuntimeV2>(
    input: VoiceSessionInputV2,
    kind: 'transcription' | 'call',
  ): Promise<RetainedVoiceSessionV2<T>> {
    const prepared = prepareVoiceSessionV2(input);
    const actions = resolveActions();
    if (!actions) throw voiceSessionErrorV2('generation_actions_unavailable');
    const lease = await actions.acquireServiceOperationLease<DesktopVoiceSessionAuthorityServiceV2>(
      {
        service: DESKTOP_VOICE_SESSION_AUTHORITY_SERVICE_V2,
        version: DESKTOP_VOICE_SESSION_AUTHORITY_VERSION_V2,
        scope: prepared.scope,
      },
    );
    if (lease.status !== 'accepted')
      throw new RuntimeV2Error(lease.reasonCode, lease.runtimeCode ?? lease.reasonCode);
    let active = true;
    let consumed = false;
    let managed: ReturnType<typeof retainVoiceSessionRuntimeV2<T>> | undefined;
    let releasePromise: Promise<void> | undefined;
    const release = (): Promise<void> => {
      if (!releasePromise) {
        active = false;
        prepared.signal.removeEventListener('abort', onAbort);
        releasePromise = (async () => {
          let failed = false;
          try {
            await managed?.dispose();
          } catch (error) {
            failed = true;
            throw error;
          } finally {
            try {
              await lease.release();
            } catch (error) {
              if (!failed) throw error;
            }
          }
        })();
        void releasePromise.catch(() => undefined);
      }
      return releasePromise;
    };
    const onAbort = () => {
      void release().catch(() => undefined);
    };
    try {
      prepared.signal.throwIfAborted();
      await lease.useService((service) => {
        if (!active || consumed) throw voiceSessionErrorV2('released');
        consumed = true;
        prepared.signal.throwIfAborted();
        if (!service || typeof service.createRuntime !== 'function')
          throw voiceSessionErrorV2('service_invalid');
        // Local has no Voice endpoint; a replacement provider must not invent protocol support.
        if (prepared.config.mode !== 'cloud' || prepared.connection.availability !== 'available')
          throw voiceSessionErrorV2('unavailable');
        const candidate = requireVoiceSessionRuntimeV2(
          service.createRuntime(prepared, kind),
          kind,
        ) as T;
        managed = retainVoiceSessionRuntimeV2(candidate, prepared);
      });
      prepared.signal.throwIfAborted();
      if (!managed) throw voiceSessionErrorV2('service_invalid');
      prepared.signal.addEventListener('abort', onAbort, { once: true });
      return Object.freeze({ runtime: managed.runtime, release });
    } catch (error) {
      await release().catch(() => undefined);
      throw error;
    }
  }
  return Object.freeze({
    acquireTranscription: (input: VoiceSessionInputV2) =>
      acquire<VoiceTranscriptionRuntime>(input, 'transcription'),
    acquireCall: (input: VoiceSessionInputV2) => acquire<VoiceCallRuntime>(input, 'call'),
  });
}
function generatedDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_VOICE_SESSION_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) throw voiceSessionErrorV2('catalog_missing');
  return entry.contract_digest;
}
