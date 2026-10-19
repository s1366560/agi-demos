import {
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from "./runtime";
import {
  desktopRendererHostDefinitionV2,
  webRendererHostDefinitionV2,
} from "./targetModules";

export type RendererContributionKindV2 =
  | "route"
  | "navigation"
  | "ui-slot"
  | "settings-page"
  | "command";
export type RendererContributionTargetV2 = "web" | "desktop-renderer";

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
  contributions: readonly RegisteredRendererContributionV2[],
) => void;

export class RendererContributionRegistryV2 {
  private readonly contributions = new Map<
    string,
    RegisteredRendererContributionV2
  >();

  constructor(
    readonly target: RendererContributionTargetV2,
    private readonly validateCandidate?: RendererContributionSetValidatorV2,
  ) {}

  register(
    sourceEntryId: string,
    contribution: RendererContributionV2,
  ): () => void {
    return this.registerAll(sourceEntryId, [contribution]);
  }

  /** Validate and install an entire feature before making any of it observable. */
  registerAll(
    sourceEntryId: string,
    contributions: readonly RendererContributionV2[],
  ): () => void {
    const candidate = new Map(this.contributions);
    const registered = contributions.map((contribution) => {
      const key = contributionKeyV2(contribution);
      if (candidate.has(key)) {
        throw new RuntimeV2Error(
          "renderer_contribution_conflict",
          `renderer_contribution_conflict:${key}`,
        );
      }
      const item = Object.freeze({
        ...contribution,
        payload: cloneAndFreezePayloadV2(contribution.payload),
        sourceEntryId,
      });
      candidate.set(key, item);
      return item;
    });
    this.validateCandidate?.(orderedContributionsV2(candidate));
    for (const item of registered)
      this.contributions.set(contributionKeyV2(item), item);
    return () => {
      for (const item of [...registered].reverse()) {
        const key = contributionKeyV2(item);
        if (this.contributions.get(key) === item)
          this.contributions.delete(key);
      }
    };
  }

  list(
    kind?: RendererContributionKindV2,
  ): readonly RegisteredRendererContributionV2[] {
    return orderedContributionsV2(this.contributions, kind);
  }
}

export const WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2 =
  "service:web.renderer-contribution-registry";
export const DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2 =
  "service:desktop-renderer.renderer-contribution-registry";

export const WEB_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2 =
  "builtin://memstack/web/renderer-contribution-registry";
export const WEB_RENDERER_CONTRIBUTION_MODULE_REF_V2 =
  "builtin://memstack/web/renderer-contribution";
export const DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2 =
  "builtin://memstack/desktop/renderer-contribution-registry";
export const DESKTOP_RENDERER_CONTRIBUTION_MODULE_REF_V2 =
  "builtin://memstack/desktop/renderer-contribution";
export const WEB_RENDERER_FEATURE_MODULE_REF_V2 =
  "builtin://memstack/web/renderer-feature";
export const DESKTOP_RENDERER_FEATURE_MODULE_REF_V2 =
  "builtin://memstack/desktop/renderer-feature";

const WEB_RENDERER_FEATURE_CONTRACT_DIGEST_V2 =
  "sha256:b6c9417ce3213545d8ab4d9c5c1932d85a047c3378b0d3cee58df6d56e0f94f9";
const DESKTOP_RENDERER_FEATURE_CONTRACT_DIGEST_V2 =
  "sha256:430c1414be547b3db0634762654367e8e5f404a1da9b3c8ae232cdc228d49ebb";

const WEB_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2 =
  "sha256:ff9b73bb2be42465e2324b562c4e57e20aa2d466c6a40909f8b0d945392d2592";
const WEB_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2 =
  "sha256:8cdc508f4bd396ada8769333d730c22adb7d76d8c2829ed3be090e225604ab42";
const DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2 =
  "sha256:91c83d16b21ca69d3044af3849b5562d8fb362393c121ea0263cf16310c8eea8";
const DESKTOP_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2 =
  "sha256:6121dd6d4838d8adb190900147921136a8ee4e48e2d14688a0df67be0ce1f451";

export function applyWebRendererContributionRegistryV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
  validateCandidate?: RendererContributionSetValidatorV2,
): void {
  requireTargetV2(config, "web");
  context.provide(
    WEB_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    new RendererContributionRegistryV2("web", validateCandidate),
  );
}

export function applyWebRendererContributionV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): () => void {
  const registry = context.require<RendererContributionRegistryV2>("registry");
  return registry.register(context.entryId, contributionFromConfigV2(config));
}

export function applyDesktopRendererContributionRegistryV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
  validateCandidate?: RendererContributionSetValidatorV2,
): void {
  requireTargetV2(config, "desktop-renderer");
  context.provide(
    DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_SERVICE_V2,
    new RendererContributionRegistryV2("desktop-renderer", validateCandidate),
  );
}

export function applyDesktopRendererContributionV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): () => void {
  const registry = context.require<RendererContributionRegistryV2>("registry");
  return registry.register(context.entryId, contributionFromConfigV2(config));
}

export function applyRendererFeatureV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): () => void {
  if (
    typeof config.id !== "string" ||
    !config.id ||
    !Number.isSafeInteger(config.order) ||
    !Array.isArray(config.contributions) ||
    config.contributions.length === 0
  ) {
    throw new RuntimeV2Error(
      "renderer_feature_config_invalid",
      "renderer_feature_config_invalid",
    );
  }
  const contributions = config.contributions.map((value: unknown) => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new RuntimeV2Error(
        "renderer_feature_config_invalid",
        "renderer_feature_config_invalid",
      );
    }
    return contributionFromConfigV2(value as Readonly<Record<string, unknown>>);
  });
  return context
    .require<RendererContributionRegistryV2>("registry")
    .registerAll(context.entryId, contributions);
}

export const webRendererFeatureDefinitionV2: PluginDefinitionV2 = Object.freeze(
  {
    moduleRef: WEB_RENDERER_FEATURE_MODULE_REF_V2,
    contractDigest: WEB_RENDERER_FEATURE_CONTRACT_DIGEST_V2,
    apply: applyRendererFeatureV2,
  },
);

export const desktopRendererFeatureDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_RENDERER_FEATURE_MODULE_REF_V2,
    contractDigest: DESKTOP_RENDERER_FEATURE_CONTRACT_DIGEST_V2,
    apply: applyRendererFeatureV2,
  });

// Recovery/configuration entry points are declared separately and cannot disable themselves.
export const webRendererManagementDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: "builtin://memstack/web/renderer-management",
    contractDigest:
      "sha256:f2e8ab8714cc096f63195af9e2de3bba9f9761d37d2d5dd82d7a7597e4213f58",
    apply: applyRendererFeatureV2,
  });
export const desktopRendererManagementDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: "builtin://memstack/desktop/renderer-management",
    contractDigest:
      "sha256:c1f83ad2a67a4df259c943827991535473390f838800631a099d8ef436c0581e",
    apply: applyRendererFeatureV2,
  });

export function createWebRendererContributionRegistryDefinitionV2(
  validateCandidate?: RendererContributionSetValidatorV2,
): PluginDefinitionV2 {
  return Object.freeze({
    moduleRef: WEB_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
    contractDigest: WEB_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2,
    apply: (context: ContextV2, config: Readonly<Record<string, unknown>>) =>
      applyWebRendererContributionRegistryV2(
        context,
        config,
        validateCandidate,
      ),
  });
}

export const webRendererContributionRegistryDefinitionV2 =
  createWebRendererContributionRegistryDefinitionV2();

export const webRendererContributionDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: WEB_RENDERER_CONTRIBUTION_MODULE_REF_V2,
    contractDigest: WEB_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2,
    apply: applyWebRendererContributionV2,
  });

export function createDesktopRendererContributionRegistryDefinitionV2(
  validateCandidate?: RendererContributionSetValidatorV2,
): PluginDefinitionV2 {
  return Object.freeze({
    moduleRef: DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_MODULE_REF_V2,
    contractDigest: DESKTOP_RENDERER_CONTRIBUTION_REGISTRY_CONTRACT_DIGEST_V2,
    apply: (context: ContextV2, config: Readonly<Record<string, unknown>>) =>
      applyDesktopRendererContributionRegistryV2(
        context,
        config,
        validateCandidate,
      ),
  });
}

export const desktopRendererContributionRegistryDefinitionV2 =
  createDesktopRendererContributionRegistryDefinitionV2();

export const desktopRendererContributionDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_RENDERER_CONTRIBUTION_MODULE_REF_V2,
    contractDigest: DESKTOP_RENDERER_CONTRIBUTION_CONTRACT_DIGEST_V2,
    apply: applyDesktopRendererContributionV2,
  });

export function createWebRendererDefinitionsV2(
  validateCandidate?: RendererContributionSetValidatorV2,
): readonly PluginDefinitionV2[] {
  return Object.freeze([
    webRendererHostDefinitionV2,
    createWebRendererContributionRegistryDefinitionV2(validateCandidate),
    webRendererContributionDefinitionV2,
    webRendererFeatureDefinitionV2,
    webRendererManagementDefinitionV2,
  ]);
}

export const webRendererDefinitionsV2 = createWebRendererDefinitionsV2();

export function createDesktopRendererDefinitionsV2(
  validateCandidate?: RendererContributionSetValidatorV2,
): readonly PluginDefinitionV2[] {
  return Object.freeze([
    desktopRendererHostDefinitionV2,
    createDesktopRendererContributionRegistryDefinitionV2(validateCandidate),
    desktopRendererContributionDefinitionV2,
    desktopRendererFeatureDefinitionV2,
    desktopRendererManagementDefinitionV2,
  ]);
}

export const desktopRendererDefinitionsV2 =
  createDesktopRendererDefinitionsV2();

function contributionFromConfigV2(
  config: Readonly<Record<string, unknown>>,
): RendererContributionV2 {
  const { id, kind, order, payload } = config;
  if (typeof id !== "string" || id.length === 0) {
    throw new RuntimeV2Error(
      "renderer_contribution_id_required",
      "renderer_contribution_id_required",
    );
  }
  if (
    kind !== "route" &&
    kind !== "navigation" &&
    kind !== "ui-slot" &&
    kind !== "settings-page" &&
    kind !== "command"
  ) {
    throw new RuntimeV2Error(
      "renderer_contribution_kind_invalid",
      "renderer_contribution_kind_invalid",
    );
  }
  if (!Number.isSafeInteger(order)) {
    throw new RuntimeV2Error(
      "renderer_contribution_order_invalid",
      "renderer_contribution_order_invalid",
    );
  }
  if (
    typeof payload !== "object" ||
    payload === null ||
    Array.isArray(payload)
  ) {
    throw new RuntimeV2Error(
      "renderer_contribution_payload_invalid",
      "renderer_contribution_payload_invalid",
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
  target: RendererContributionTargetV2,
): void {
  if (config.target !== target) {
    throw new RuntimeV2Error(
      "renderer_contribution_target_invalid",
      `renderer_contribution_target_invalid:${target}`,
    );
  }
}

function contributionKeyV2(contribution: RendererContributionV2): string {
  return `${contribution.kind}:${contribution.id}`;
}

function orderedContributionsV2(
  contributions: ReadonlyMap<string, RegisteredRendererContributionV2>,
  kind?: RendererContributionKindV2,
): readonly RegisteredRendererContributionV2[] {
  return Object.freeze(
    [...contributions.values()]
      .filter(
        (contribution) => kind === undefined || contribution.kind === kind,
      )
      .sort(
        (left, right) =>
          left.order - right.order ||
          contributionKeyV2(left).localeCompare(contributionKeyV2(right)),
      ),
  );
}

function cloneAndFreezePayloadV2(
  payload: Readonly<Record<string, unknown>>,
): Readonly<Record<string, unknown>> {
  return deepFreezeV2(structuredClone(payload)) as Readonly<
    Record<string, unknown>
  >;
}

function deepFreezeV2(value: unknown): unknown {
  if (Array.isArray(value)) {
    for (const item of value) deepFreezeV2(item);
    return Object.freeze(value);
  }
  if (typeof value === "object" && value !== null) {
    for (const item of Object.values(value)) deepFreezeV2(item);
    return Object.freeze(value);
  }
  return value;
}
