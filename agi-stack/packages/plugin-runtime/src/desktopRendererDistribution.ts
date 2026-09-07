import { parseControlPlaneDistributionV2, type ControlPlaneDistributionV2 } from './distribution';
import { PluginProtocolV2Error } from './errors';
import type { ProfileSnapshotV2, SnapshotApplyReceiptV2 } from './generated';
import type { RendererPluginRuntimeV2 } from './renderer';
import { parseProfileSnapshotV2 } from './validate';

export type DesktopRendererDistributionV2 =
  | Readonly<{ source: 'local'; snapshot: ProfileSnapshotV2 }>
  | Readonly<{ source: 'cloud'; distribution: ControlPlaneDistributionV2 }>;

type DesktopRendererDistributionIdentityV2 =
  | Readonly<{ source: 'local'; digest: string }>
  | Readonly<{ source: 'cloud'; digest: string; version: number }>;

export async function parseDesktopRendererDistributionV2(
  value: unknown
): Promise<DesktopRendererDistributionV2> {
  const payload = distributionObjectV2(value);
  if (payload.source === 'local') {
    exactDistributionKeysV2(payload, ['source', 'snapshot']);
    return {
      source: 'local',
      snapshot: await parseProfileSnapshotV2(payload.snapshot),
    };
  }
  if (payload.source === 'cloud') {
    exactDistributionKeysV2(payload, ['source', 'distribution']);
    return {
      source: 'cloud',
      distribution: await parseControlPlaneDistributionV2(payload.distribution),
    };
  }
  distributionFailureV2('desktop renderer distribution source must be local or cloud');
}

export class DesktopRendererDistributionReconcilerV2 {
  private activeIdentity: DesktopRendererDistributionIdentityV2 | undefined;
  private operationTail: Promise<void> = Promise.resolve();
  private closePromise: Promise<void> | null = null;

  constructor(private readonly runtime: RendererPluginRuntimeV2) {}

  async apply(value: unknown): Promise<SnapshotApplyReceiptV2 | undefined> {
    if (this.closePromise !== null) await this.closePromise;
    const applyPromise = this.operationTail.then(() => this.applyDistribution(value));
    this.operationTail = applyPromise.then(
      () => undefined,
      () => undefined
    );
    return applyPromise;
  }

  async close(): Promise<void> {
    if (this.closePromise !== null) return this.closePromise;
    const closePromise = this.closeRuntime();
    this.closePromise = closePromise;
    try {
      await closePromise;
    } finally {
      if (this.closePromise === closePromise) this.closePromise = null;
    }
  }

  private async applyDistribution(value: unknown): Promise<SnapshotApplyReceiptV2 | undefined> {
    const distribution = await parseDesktopRendererDistributionV2(value);
    const identity = distributionIdentityV2(distribution);
    if (
      sameDistributionIdentityV2(identity, this.activeIdentity) &&
      this.runtime.getSnapshot()?.snapshot.digest === identity.digest
    ) {
      return undefined;
    }

    if (distribution.source === 'local') {
      await this.runtime.replaceBaseline(distribution.snapshot);
      this.activeIdentity = identity;
      return undefined;
    }

    const receipt = await this.runtime.apply(distribution.distribution);
    if (receipt.status === 'ack') this.activeIdentity = identity;
    return receipt;
  }

  private async closeRuntime(): Promise<void> {
    await this.operationTail;
    await this.runtime.close();
    this.activeIdentity = undefined;
  }
}

function distributionObjectV2(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    distributionFailureV2('desktop renderer distribution must be an object');
  }
  return value as Record<string, unknown>;
}

function exactDistributionKeysV2(
  payload: Record<string, unknown>,
  expected: readonly string[]
): void {
  const expectedKeys = new Set(expected);
  for (const key of Object.keys(payload)) {
    if (!expectedKeys.has(key)) distributionFailureV2(`unknown field: ${key}`);
  }
  for (const key of expected) {
    if (!(key in payload)) distributionFailureV2(`missing field: ${key}`);
  }
}

function distributionIdentityV2(
  distribution: DesktopRendererDistributionV2
): DesktopRendererDistributionIdentityV2 {
  if (distribution.source === 'local') {
    return { source: 'local', digest: distribution.snapshot.digest };
  }
  return {
    source: 'cloud',
    digest: distribution.distribution.snapshot.digest,
    version: distribution.distribution.envelope.version,
  };
}

function sameDistributionIdentityV2(
  left: DesktopRendererDistributionIdentityV2,
  right: DesktopRendererDistributionIdentityV2 | undefined
): boolean {
  if (right === undefined || left.source !== right.source || left.digest !== right.digest) {
    return false;
  }
  return left.source === 'local' || (right.source === 'cloud' && left.version === right.version);
}

function distributionFailureV2(message: string): never {
  throw new PluginProtocolV2Error('desktop_renderer_distribution_invalid', message);
}
