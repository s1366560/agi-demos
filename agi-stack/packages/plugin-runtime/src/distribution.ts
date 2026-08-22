import { PluginProtocolV2Error } from "./errors";
import type {
  ControlPlaneEnvelopeV2,
  ProfileSnapshotV2,
  SnapshotApplyReceiptV2,
} from "./generated";
import { GenerationManagerV2, LoaderV2 } from "./runtime";
import { parseProfileSnapshotV2, PLUGIN_PROFILE_TYPE_URL_V2 } from "./validate";

export interface PluginGenerationDescriptorV2 {
  readonly profile_id: string;
  readonly generation: number;
  readonly digest: string;
}

export interface ControlPlaneDistributionV2 {
  readonly schema_version: 2;
  readonly descriptor: PluginGenerationDescriptorV2;
  readonly snapshot: ProfileSnapshotV2;
  readonly envelope: ControlPlaneEnvelopeV2;
}

export async function parseControlPlaneDistributionV2(
  value: unknown,
): Promise<ControlPlaneDistributionV2> {
  const payload = objectValue(value, "distribution");
  if (payload.schema_version !== 2) {
    throw new PluginProtocolV2Error(
      "incompatible_schema_version",
      "plugin distribution schema_version must be 2; v1 is not accepted",
    );
  }
  exactKeys(payload, ["schema_version", "descriptor", "snapshot", "envelope"]);
  const descriptor = parseDescriptor(payload.descriptor);
  const envelope = parseEnvelope(payload.envelope);
  const snapshot = await parseProfileSnapshotV2(payload.snapshot);

  if (
    descriptor.profile_id !== snapshot.profile_id ||
    descriptor.generation !== snapshot.generation ||
    descriptor.digest !== snapshot.digest
  ) {
    mismatch("descriptor does not match snapshot");
  }
  if (envelope.snapshot_digest !== snapshot.digest) {
    mismatch("envelope digest does not match snapshot");
  }
  if (envelope.type_url !== PLUGIN_PROFILE_TYPE_URL_V2) {
    mismatch("envelope type_url is incompatible");
  }

  return {
    schema_version: 2,
    descriptor,
    snapshot,
    envelope,
  };
}

export class PluginSnapshotReconcilerV2 {
  readonly manager = new GenerationManagerV2();
  private appliedVersion: number | null = null;
  private appliedDigest: string | null = null;
  private bootstrapPromise: Promise<void> | null = null;
  private applyTail: Promise<void> = Promise.resolve();
  private closePromise: Promise<void> | null = null;

  constructor(private readonly loader: LoaderV2) {}

  async bootstrap(snapshot: ProfileSnapshotV2): Promise<void> {
    if (this.closePromise !== null) await this.closePromise;
    if (this.manager.current !== undefined) return;
    if (this.bootstrapPromise !== null) return this.bootstrapPromise;

    const bootstrapPromise = this.publishBootstrap(snapshot);
    this.bootstrapPromise = bootstrapPromise;
    try {
      await bootstrapPromise;
    } finally {
      if (this.bootstrapPromise === bootstrapPromise) this.bootstrapPromise = null;
    }
  }

  async apply(
    distribution: ControlPlaneDistributionV2,
  ): Promise<SnapshotApplyReceiptV2> {
    if (this.closePromise !== null) await this.closePromise;
    const applyPromise = this.applyTail.then(() =>
      this.applyDistribution(distribution),
    );
    this.applyTail = applyPromise.then(
      () => undefined,
      () => undefined,
    );
    return applyPromise;
  }

  private async applyDistribution(
    distribution: ControlPlaneDistributionV2,
  ): Promise<SnapshotApplyReceiptV2> {
    if (this.appliedVersion !== null) {
      if (distribution.envelope.version < this.appliedVersion) {
        return this.nack(
          distribution,
          "stale_version",
          "snapshot version is stale",
        );
      }
      if (distribution.envelope.version === this.appliedVersion) {
        if (this.appliedDigest === distribution.snapshot.digest)
          return this.ack(distribution);
        return this.nack(
          distribution,
          "version_conflict",
          "snapshot version already belongs to another digest",
        );
      }
    }

    try {
      const generation = await this.loader.stage(distribution.snapshot);
      await this.manager.publish(generation);
      this.appliedVersion = distribution.envelope.version;
      this.appliedDigest = distribution.snapshot.digest;
      return this.ack(distribution);
    } catch (error) {
      return this.nack(
        distribution,
        "generation_apply_failed",
        errorMessage(error),
      );
    }
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

  private async publishBootstrap(snapshot: ProfileSnapshotV2): Promise<void> {
    const generation = await this.loader.stage(snapshot);
    if (this.manager.current !== undefined) {
      await generation.dispose();
      return;
    }
    try {
      await this.manager.publish(generation);
    } catch (error) {
      await generation.dispose();
      throw error;
    }
  }

  private async closeRuntime(): Promise<void> {
    if (this.bootstrapPromise !== null) {
      await this.bootstrapPromise.catch(() => undefined);
    }
    await this.applyTail;
    await this.manager.close();
    this.appliedVersion = null;
    this.appliedDigest = null;
  }

  private ack(
    distribution: ControlPlaneDistributionV2,
  ): SnapshotApplyReceiptV2 {
    return {
      status: "ack",
      requested_version: distribution.envelope.version,
      requested_digest: distribution.snapshot.digest,
      applied_version: this.appliedVersion,
      applied_digest: this.appliedDigest,
      error_code: null,
      error_message: null,
    };
  }

  private nack(
    distribution: ControlPlaneDistributionV2,
    errorCode: string,
    errorMessageValue: string,
  ): SnapshotApplyReceiptV2 {
    return {
      status: "nack",
      requested_version: distribution.envelope.version,
      requested_digest: distribution.snapshot.digest,
      applied_version: this.appliedVersion,
      applied_digest: this.appliedDigest,
      error_code: errorCode,
      error_message: errorMessageValue,
    };
  }
}

function parseDescriptor(value: unknown): PluginGenerationDescriptorV2 {
  const payload = objectValue(value, "descriptor");
  exactKeys(payload, ["profile_id", "generation", "digest"]);
  return {
    profile_id: nonEmptyString(payload.profile_id, "descriptor.profile_id"),
    generation: positiveInteger(payload.generation, "descriptor.generation"),
    digest: digestValue(payload.digest, "descriptor.digest"),
  };
}

function parseEnvelope(value: unknown): ControlPlaneEnvelopeV2 {
  const payload = objectValue(value, "envelope");
  exactKeys(payload, ["version", "nonce", "snapshot_digest", "type_url"]);
  return {
    version: positiveInteger(payload.version, "envelope.version"),
    nonce: nonEmptyString(payload.nonce, "envelope.nonce"),
    snapshot_digest: digestValue(
      payload.snapshot_digest,
      "envelope.snapshot_digest",
    ),
    type_url: nonEmptyString(payload.type_url, "envelope.type_url"),
  };
}

function objectValue(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    schemaFailure(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  payload: Record<string, unknown>,
  expected: readonly string[],
): void {
  const expectedKeys = new Set(expected);
  for (const key of Object.keys(payload)) {
    if (!expectedKeys.has(key)) schemaFailure(`unknown field: ${key}`);
  }
  for (const key of expected) {
    if (!(key in payload)) schemaFailure(`missing field: ${key}`);
  }
}

function nonEmptyString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) {
    schemaFailure(`${name} must be a non-empty string`);
  }
  return value as string;
}

function positiveInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1) {
    schemaFailure(`${name} must be a positive integer`);
  }
  return value as number;
}

function digestValue(value: unknown, name: string): string {
  const digest = nonEmptyString(value, name);
  if (!/^[0-9a-f]{64}$/.test(digest)) schemaFailure(`${name} is invalid`);
  return digest;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function schemaFailure(message: string): never {
  throw new PluginProtocolV2Error("schema_validation_failed", message);
}

function mismatch(message: string): never {
  throw new PluginProtocolV2Error("distribution_mismatch", message);
}
