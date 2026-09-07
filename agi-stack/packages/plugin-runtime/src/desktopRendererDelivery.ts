import { parseDesktopRendererDistributionV2 } from "./desktopRendererDistribution";
import {
  parseControlPlaneDistributionV2,
  type ControlPlaneDistributionV2,
} from "./distribution";
import { PluginProtocolV2Error } from "./errors";
import type { ProfileSnapshotV2, SnapshotApplyReceiptV2 } from "./generated";
import type { RendererPluginRuntimeV2 } from "./renderer";

export type DesktopRendererDeliveryV2 =
  | Readonly<{ source: "local"; snapshot: ProfileSnapshotV2 }>
  | Readonly<{
      source: "cloud";
      distribution: ControlPlaneDistributionV2;
      delivery_token: string;
      authority_id: string;
    }>;

export type SubmitDesktopRendererReceiptV2 = (
  token: string,
  receipt: SnapshotApplyReceiptV2,
) => Promise<void>;

export async function parseDesktopRendererDeliveryV2(
  value: unknown,
): Promise<DesktopRendererDeliveryV2> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    invalidDelivery();
  const payload = value as Record<string, unknown>;
  if (payload.source === "local") {
    const local = await parseDesktopRendererDistributionV2(payload);
    if (local.source === "local") return local;
  }
  if (payload.source !== "cloud") invalidDelivery();
  const keys = ["source", "distribution", "delivery_token", "authority_id"];
  if (
    Object.keys(payload).length !== keys.length ||
    !keys.every((key) => Object.hasOwn(payload, key))
  ) {
    invalidDelivery();
  }
  for (const key of ["delivery_token", "authority_id"] as const) {
    const field = payload[key];
    if (
      typeof field !== "string" ||
      field.length === 0 ||
      field.trim() !== field
    )
      invalidDelivery();
  }
  return {
    source: "cloud",
    distribution: await parseControlPlaneDistributionV2(payload.distribution),
    delivery_token: payload.delivery_token as string,
    authority_id: payload.authority_id as string,
  };
}

/** Serializes application and receipt delivery without coupling publication to network success. */
export class DesktopRendererDeliveryReconcilerV2 {
  private tail: Promise<void> = Promise.resolve();
  private closing: Promise<void> | undefined;
  private authority: string | undefined;
  private localDigest: string | undefined;
  private cached: { key: string; receipt: SnapshotApplyReceiptV2 } | undefined;

  constructor(
    private readonly runtime: RendererPluginRuntimeV2,
    private readonly submitReceipt: SubmitDesktopRendererReceiptV2,
    private readonly retireDelivery: () => Promise<void> = async () =>
      undefined,
  ) {}

  apply(value: unknown): Promise<SnapshotApplyReceiptV2 | undefined> {
    const result = this.tail.then(() => this.applyDelivery(value));
    this.tail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  close(): Promise<void> {
    if (this.closing !== undefined) return this.closing;
    const pending = this.tail;
    const result = Promise.resolve().then(async () => {
      const errors: unknown[] = [];
      try {
        await this.retireDelivery();
      } catch (error) {
        errors.push(error);
      }
      await pending;
      try {
        await this.runtime.close();
      } catch (error) {
        errors.push(error);
      } finally {
        this.authority = undefined;
        this.localDigest = undefined;
        this.cached = undefined;
      }
      if (errors.length === 1) throw errors[0];
      if (errors.length > 1)
        throw new AggregateError(errors, "renderer delivery close failed");
    });
    this.closing = result;
    this.tail = result.then(
      () => undefined,
      () => undefined,
    );
    void result.then(
      () => {
        if (this.closing === result) this.closing = undefined;
      },
      () => {
        if (this.closing === result) this.closing = undefined;
      },
    );
    return result;
  }

  private async applyDelivery(
    value: unknown,
  ): Promise<SnapshotApplyReceiptV2 | undefined> {
    const delivery = await parseDesktopRendererDeliveryV2(value);
    if (delivery.source === "local") {
      if (
        this.authority !== undefined ||
        this.localDigest !== delivery.snapshot.digest ||
        this.runtime.getSnapshot()?.snapshot.digest !== delivery.snapshot.digest
      ) {
        await this.runtime.replaceBaseline(delivery.snapshot);
      }
      this.authority = undefined;
      this.localDigest = delivery.snapshot.digest;
      this.cached = undefined;
      return undefined;
    }
    if (this.authority !== delivery.authority_id) {
      try {
        await this.runtime.close();
      } finally {
        this.authority = undefined;
        this.localDigest = undefined;
        this.cached = undefined;
      }
      this.authority = delivery.authority_id;
    }
    const { envelope, snapshot } = delivery.distribution;
    const key = JSON.stringify([
      delivery.authority_id,
      envelope.nonce,
      envelope.version,
      snapshot.digest,
      delivery.delivery_token,
    ]);
    if (this.cached?.key !== key) {
      const receipt = await this.runtime.apply(delivery.distribution);
      this.cached = { key, receipt };
    }
    const receipt = this.cached.receipt;
    await this.submitReceipt(delivery.delivery_token, receipt);
    return receipt;
  }
}

function invalidDelivery(): never {
  throw new PluginProtocolV2Error(
    "desktop_renderer_delivery_invalid",
    "desktop renderer delivery is invalid",
  );
}
