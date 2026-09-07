import { RuntimeV2Error, type ContextV2, type PluginDefinitionV2 } from './runtime';
import { desktopRendererHostDefinitionV2, webRendererHostDefinitionV2 } from './targetModules';

export type RendererContributionKindV2 = 'route' | 'navigation' | 'ui-slot';
export type RendererContributionTargetV2 = 'web' | 'desktop-renderer';

export interface RendererContributionV2 {
  readonly id: string;
  readonly kind: RendererContributionKindV2;
  readonly order: number;
  readonly payload: Readonly<Record<string, unknown>>;
}

export interface RegisteredRendererContributionV2 extends RendererContributionV2 {
  readonly sourceEntryId: string;
}

export type RendererContributionSetValidatorV2 = (
  contributions: readonly RegisteredRendererContributionV2[]
) => void;

export class RendererContributionRegistryV2 {
  private readonly contributions = new Map<string, RegisteredRendererContributionV2>();

  constructor(
    readonly target: RendererContributionTargetV2,
    private readonly validateCandidate?: RendererContributionSetValidatorV2
  ) {}

  register(sourceEntryId: string, contribution: RendererContributionV2): () => void {
    const key = contributionKeyV2(contribution);
    if (this.contributions.has(key)) {
      throw new RuntimeV2Error(
        'renderer_contribution_conflict',
        `renderer_contribution_conflict:${key}`
      );
    }
    const registered = Object.freeze({
      ...contribution,
      payload: cloneAndFreezePayloadV2(contribution.payload),
      sourceEntryId,
    });
    const candidate = new Map(this.contributions);
    candidate.set(key, registered);
    this.validateCandidate?.(orderedContributionsV2(candidate));
    this.contributions.set(key, registered);
    return () => {
      if (this.contributions.get(key) === registered) {
        this.contributions.delete(key);
      }
    };
  }

  list(kind?: RendererContributionKindV2): readonly RegisteredRendererContributionV2[] {
    return orderedContributionsV2(this.contributions, kind);
  }
}

export const WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2 =
  'service:web.renderer-contribution-registry';
export const DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2 =
  'service:desktop-renderer.renderer-contribution-registry';

export const WEB_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2 =
  'builtin://memstack/web/renderer-contribution-registry';
export const WEB_RENDERER_CONTRIBUTION_MODULE_REF_V2 =
  'builtin://memstack/web/renderer-contribution';
export const DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2 =
  'builtin://memstack/desktop/renderer-contribution-registry';
export const DESKTOP_RENDERER_CONTRIBUTION_MODULE_REF_V2 =
  'builtin://memstack/desktop/renderer-contribution';

const WEB_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2 =
  'sha256:ff9b73bb2be42465e2324b562c4e57e20aa2d466c6a40909f8b0d945392d2592';
const WEB_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2 =
  'sha256:a1adf76747c59abd6fc897622f8a0fc318f26a52d5cfa3c5659fcf79d936fbd7';
const DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2 =
  'sha256:91c83d16b21ca69d3044af3849b5562d8fb362393c121ea0263cf16310c8eea8';
const DESKTOP_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2 =
  'sha256:ee51655e1a4136786327a1a62480ce42455c37250a23e89c4c744ec07229724e';

export function applyWebRendererContributionRegistryV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
  validateCandidate?: RendererContributionSetValidatorV2
): void {
  requireTargetV2(config, 'web');
  context.provide(
    WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    new RendererContributionRegistryV2('web', validateCandidate)
  );
}

export function applyWebRendererContributionV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): () => void {
  const registry = context.require<RendererContributionRegistryV2>('registry');
  return registry.register(context.entryId, contributionFromConfigV2(config));
}

export function applyDesktopRendererContributionRegistryV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
  validateCandidate?: RendererContributionSetValidatorV2
): void {
  requireTargetV2(config, 'desktop-renderer');
  context.provide(
    DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    new RendererContributionRegistryV2('desktop-renderer', validateCandidate)
  );
}

export function applyDesktopRendererContributionV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>
): () => void {
  const registry = context.require<RendererContributionRegistryV2>('registry');
  return registry.register(context.entryId, contributionFromConfigV2(config));
}

export function createWebRendererContributionRegistryDefinitionV2(
  validateCandidate?: RendererContributionSetValidatorV2
): PluginDefinitionV2 {
  return Object.freeze({
    moduleRef: WEB_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
    contractDigest: WEB_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2,
    apply: (context: ContextV2, config: Readonly<Record<string, unknown>>) =>
      applyWebRendererContributionRegistryV2(context, config, validateCandidate),
  });
}

export const webRendererContributionRegistryDefinitionV2 =
  createWebRendererContributionRegistryDefinitionV2();

export const webRendererContributionDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: WEB_RENDERER_CONTRIBUTION_MODULE_REF_V2,
  contractDigest: WEB_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2,
  apply: applyWebRendererContributionV2,
});

export function createDesktopRendererContributionRegistryDefinitionV2(
  validateCandidate?: RendererContributionSetValidatorV2
): PluginDefinitionV2 {
  return Object.freeze({
    moduleRef: DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
    contractDigest: DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2,
    apply: (context: ContextV2, config: Readonly<Record<string, unknown>>) =>
      applyDesktopRendererContributionRegistryV2(context, config, validateCandidate),
  });
}

export const desktopRendererContributionRegistryDefinitionV2 =
  createDesktopRendererContributionRegistryDefinitionV2();

export const desktopRendererContributionDefinitionV2: PluginDefinitionV2 = Object.freeze({
  moduleRef: DESKTOP_RENDERER_CONTRIBUTION_MODULE_REF_V2,
  contractDigest: DESKTOP_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2,
  apply: applyDesktopRendererContributionV2,
});

export function createWebRendererDefinitionsV2(
  validateCandidate?: RendererContributionSetValidatorV2
): readonly PluginDefinitionV2[] {
  return Object.freeze([
    webRendererHostDefinitionV2,
    createWebRendererContributionRegistryDefinitionV2(validateCandidate),
    webRendererContributionDefinitionV2,
  ]);
}

export const webRendererDefinitionsV2 = createWebRendererDefinitionsV2();

export function createDesktopRendererDefinitionsV2(
  validateCandidate?: RendererContributionSetValidatorV2
): readonly PluginDefinitionV2[] {
  return Object.freeze([
    desktopRendererHostDefinitionV2,
    createDesktopRendererContributionRegistryDefinitionV2(validateCandidate),
    desktopRendererContributionDefinitionV2,
  ]);
}

export const desktopRendererDefinitionsV2 = createDesktopRendererDefinitionsV2();

function contributionFromConfigV2(
  config: Readonly<Record<string, unknown>>
): RendererContributionV2 {
  const { id, kind, order, payload } = config;
  if (typeof id !== 'string' || id.length === 0) {
    throw new RuntimeV2Error(
      'renderer_contribution_id_required',
      'renderer_contribution_id_required'
    );
  }
  if (kind !== 'route' && kind !== 'navigation' && kind !== 'ui-slot') {
    throw new RuntimeV2Error(
      'renderer_contribution_kind_invalid',
      'renderer_contribution_kind_invalid'
    );
  }
  if (!Number.isSafeInteger(order)) {
    throw new RuntimeV2Error(
      'renderer_contribution_order_invalid',
      'renderer_contribution_order_invalid'
    );
  }
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
    throw new RuntimeV2Error(
      'renderer_contribution_payload_invalid',
      'renderer_contribution_payload_invalid'
    );
  }
  return Object.freeze({
    id,
    kind,
    order: order as number,
    payload: payload as Readonly<Record<string, unknown>>,
  });
}

function requireTargetV2(
  config: Readonly<Record<string, unknown>>,
  target: RendererContributionTargetV2
): void {
  if (config.target !== target) {
    throw new RuntimeV2Error(
      'renderer_contribution_target_invalid',
      `renderer_contribution_target_invalid:${target}`
    );
  }
}

function contributionKeyV2(contribution: RendererContributionV2): string {
  return `${contribution.kind}:${contribution.id}`;
}

function orderedContributionsV2(
  contributions: ReadonlyMap<string, RegisteredRendererContributionV2>,
  kind?: RendererContributionKindV2
): readonly RegisteredRendererContributionV2[] {
  return Object.freeze(
    [...contributions.values()]
      .filter((contribution) => kind === undefined || contribution.kind === kind)
      .sort(
        (left, right) =>
          left.order - right.order ||
          contributionKeyV2(left).localeCompare(contributionKeyV2(right))
      )
  );
}

function cloneAndFreezePayloadV2(
  payload: Readonly<Record<string, unknown>>
): Readonly<Record<string, unknown>> {
  return deepFreezeV2(structuredClone(payload)) as Readonly<Record<string, unknown>>;
}

function deepFreezeV2(value: unknown): unknown {
  if (Array.isArray(value)) {
    for (const item of value) deepFreezeV2(item);
    return Object.freeze(value);
  }
  if (typeof value === 'object' && value !== null) {
    for (const item of Object.values(value)) deepFreezeV2(item);
    return Object.freeze(value);
  }
  return value;
}
