import type { ContextV2, PluginDefinitionV2 } from './runtime';

export const WEB_RENDERER_HOST_MODULE_REF_V2 = 'builtin://memstack/web/renderer-host';
export const DESKTOP_RENDERER_HOST_MODULE_REF_V2 =
  'builtin://memstack/desktop/renderer-host';
export const WEB_RENDERER_HOST_SERVICE_V2 = 'service:web.renderer-contributions';
export const DESKTOP_RENDERER_HOST_SERVICE_V2 =
  'service:desktop-renderer.renderer-contributions';

const WEB_RENDERER_HOST_CONTRACT_DIGEST_V2 =
  'sha256:738916402aa90851926cd84da1bfb89996eeb37b3776f7156c91fcc0bf46822b';
const DESKTOP_RENDERER_HOST_CONTRACT_DIGEST_V2 =
  'sha256:eecbc11fe07bb5cf90fe46909601ba112a22db2ad444339f93717d3f37703aa2';

export interface TargetHostDescriptorV2 {
  readonly target: 'web' | 'desktop-renderer';
  readonly strategy: string;
}

export function applyWebRendererHostV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  context.provide(WEB_RENDERER_HOST_SERVICE_V2, {
    target: 'web',
    strategy: requiredStrategyV2(config),
  } satisfies TargetHostDescriptorV2);
}

export function applyDesktopRendererHostV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): void {
  context.provide(DESKTOP_RENDERER_HOST_SERVICE_V2, {
    target: 'desktop-renderer',
    strategy: requiredStrategyV2(config),
  } satisfies TargetHostDescriptorV2);
}

export const webRendererHostDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: WEB_RENDERER_HOST_MODULE_REF_V2,
  contractDigest: WEB_RENDERER_HOST_CONTRACT_DIGEST_V2,
  apply: applyWebRendererHostV2,
});

export const desktopRendererHostDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_RENDERER_HOST_MODULE_REF_V2,
  contractDigest: DESKTOP_RENDERER_HOST_CONTRACT_DIGEST_V2,
  apply: applyDesktopRendererHostV2,
});

function requiredStrategyV2(config: Readonly<Record<string, unknown>>): string {
  const strategy = config.strategy;
  if (typeof strategy !== 'string' || strategy.length === 0) {
    throw new Error('target_host_strategy_required');
  }
  return strategy;
}
