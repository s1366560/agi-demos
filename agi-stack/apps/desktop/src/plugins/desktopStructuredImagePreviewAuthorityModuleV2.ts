import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';
import type { DesktopRuntimeConfig } from '../types';
import type { DesktopRendererGenerationActionsV2 } from './desktopRendererGenerationContextV2';
import {
  freezeImagePreviewConfigV2,
  freezeImagePreviewOwnerV2,
  imagePreviewErrorV2,
  prepareStructuredImagePreviewV2,
  requireStructuredImagePreviewBlobV2,
  type ImagePreviewOwnerV2,
  type StructuredImagePreviewInputV2,
  type PreparedStructuredImagePreviewV2,
} from './desktopStructuredImagePreviewContractV2';
import { loadStructuredImagePreviewHttpV2 } from './desktopStructuredImagePreviewHttpProjectionV2';
export type {
  ImagePreviewOwnerV2,
  StructuredImagePreviewInputV2,
} from './desktopStructuredImagePreviewContractV2';

export const DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/structured-image-preview-authority';
export const DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.structured-image-preview-authority';
export const DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_VERSION_V2 = '1.0.0';
export interface StructuredImagePreviewClientV2 {
  readonly owner: ImagePreviewOwnerV2;
  loadImage(input: StructuredImagePreviewInputV2): Promise<Blob>;
}
export interface StructuredImagePreviewAuthorityServiceV2 {
  loadImage(input: PreparedStructuredImagePreviewV2): Promise<Blob>;
}
export function applyDesktopStructuredImagePreviewAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (config.strategy !== 'structured-preview-url' || Object.keys(config).length !== 1)
    throw imagePreviewErrorV2('config_invalid');
  context.provide(
    DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_SERVICE_V2,
    Object.freeze({ loadImage: loadStructuredImagePreviewHttpV2 }),
  );
}
export const desktopStructuredImagePreviewAuthorityDefinitionV2: PluginDefinitionV2 = Object.freeze(
  {
    moduleRef: DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedDigestV2(),
    apply: applyDesktopStructuredImagePreviewAuthorityV2,
  },
);
export function createDesktopStructuredImagePreviewClientV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
  config: DesktopRuntimeConfig,
  owner: ImagePreviewOwnerV2,
): StructuredImagePreviewClientV2 {
  const frozenConfig = freezeImagePreviewConfigV2(config);
  const frozenOwner = freezeImagePreviewOwnerV2(owner);
  return Object.freeze({
    owner: frozenOwner,
    async loadImage(input: StructuredImagePreviewInputV2): Promise<Blob> {
      const prepared = prepareStructuredImagePreviewV2(frozenConfig, frozenOwner, input);
      const actions = resolveActions();
      if (!actions) throw imagePreviewErrorV2('generation_actions_unavailable');
      const lease =
        await actions.acquireServiceOperationLease<StructuredImagePreviewAuthorityServiceV2>({
          service: DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_SERVICE_V2,
          version: DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_VERSION_V2,
          scope: prepared.scope,
        });
      if (lease.status !== 'accepted')
        throw new RuntimeV2Error(lease.reasonCode, lease.runtimeCode ?? lease.reasonCode);
      let active = true;
      let consumed = false;
      let failed = false;
      let pending: Promise<Blob> | undefined;
      try {
        prepared.signal.throwIfAborted();
        await lease.useService((service) => {
          if (!active || consumed) throw imagePreviewErrorV2('operation_released');
          consumed = true;
          prepared.signal.throwIfAborted();
          if (!service || typeof service.loadImage !== 'function')
            throw imagePreviewErrorV2('service_invalid');
          pending = (async () => {
            const value = await service.loadImage(prepared);
            prepared.signal.throwIfAborted();
            return requireStructuredImagePreviewBlobV2(value);
          })();
          void pending.catch(() => undefined);
          return pending;
        });
        if (!pending) throw imagePreviewErrorV2('service_invalid');
        return await pending;
      } catch (error) {
        failed = true;
        throw error;
      } finally {
        active = false;
        if (pending) await pending.catch(() => undefined);
        try {
          await lease.release();
        } catch (error) {
          if (!failed) throw error;
        }
      }
    },
  });
}
function generatedDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (item) => item.module_ref === DESKTOP_STRUCTURED_IMAGE_PREVIEW_AUTHORITY_MODULE_REF_V2,
  );
  if (!entry) throw imagePreviewErrorV2('catalog_missing');
  return entry.contract_digest;
}
