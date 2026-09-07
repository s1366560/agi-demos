import { PluginProtocolV2Error } from "./errors";
import type { ProfileSnapshotV2 } from "./generated";
import type { RendererPluginRuntimeV2 } from "./renderer";
import { parseProfileSnapshotV2 } from "./validate";

export interface WebPublicViewV2 {
  readonly schema_version: 2;
  readonly target: "web";
  readonly view_id: string;
  readonly snapshot: ProfileSnapshotV2;
}

/** A public view is a distinct snapshot, never a workload publication or receipt. */
export async function parseWebPublicViewV2(
  value: unknown,
): Promise<WebPublicViewV2> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    invalidView();
  const payload = value as Record<string, unknown>;
  const keys = ["schema_version", "target", "view_id", "snapshot"];
  if (
    Object.keys(payload).length !== keys.length ||
    !keys.every((key) => Object.hasOwn(payload, key)) ||
    payload.schema_version !== 2 ||
    payload.target !== "web" ||
    typeof payload.view_id !== "string" ||
    payload.view_id.length === 0 ||
    payload.view_id.trim() !== payload.view_id
  )
    invalidView();
  const snapshot = await parseProfileSnapshotV2(payload.snapshot);
  if (
    snapshot.profile_id !== "web-public-view-v2" ||
    snapshot.entries.some((entry) => entry.scope.kind !== "root") ||
    snapshot.manifests.some((manifest) =>
      manifest.modules.some(
        (module) => module.targets.length !== 1 || module.targets[0] !== "web",
      ),
    )
  )
    invalidView();
  return {
    schema_version: 2,
    target: "web",
    view_id: payload.view_id as string,
    snapshot,
  };
}

/** Call close on authentication identity changes; view_id itself grants no authority. */
export class WebPublicViewReconcilerV2 {
  private tail: Promise<void> = Promise.resolve();
  private closing: Promise<void> | undefined;
  private identity: { viewId: string; digest: string } | undefined;

  constructor(private readonly runtime: RendererPluginRuntimeV2) {}

  apply(value: unknown): Promise<void> {
    this.closing = undefined;
    const result = this.tail.then(async () => {
      const view = await parseWebPublicViewV2(value);
      if (
        this.identity?.viewId === view.view_id &&
        this.identity.digest === view.snapshot.digest &&
        this.runtime.getSnapshot()?.snapshot.digest === view.snapshot.digest
      )
        return;
      await this.runtime.replaceBaseline(view.snapshot);
      this.identity = { viewId: view.view_id, digest: view.snapshot.digest };
    });
    this.tail = result.catch(() => undefined);
    return result;
  }

  close(): Promise<void> {
    if (this.closing !== undefined) return this.closing;
    const result = this.tail.then(async () => {
      try {
        await this.runtime.close();
      } finally {
        this.identity = undefined;
      }
    });
    this.closing = result;
    this.tail = result.catch(() => undefined);
    return result;
  }
}

function invalidView(): never {
  throw new PluginProtocolV2Error(
    "web_public_view_invalid",
    "Web public view is invalid",
  );
}
