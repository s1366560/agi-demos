import {
  parseControlPlaneDistributionV2,
  PluginSnapshotReconcilerV2,
} from "./distribution";
import type { DataPlaneTargetV2, SnapshotApplyReceiptV2 } from "./generated";
import {
  LoaderV2,
  type PluginDefinitionV2,
  type RuntimeGenerationV2,
} from "./runtime";
import { parseProfileSnapshotV2 } from "./validate";

export type RendererDataPlaneTargetV2 = Extract<
  DataPlaneTargetV2,
  "web" | "desktop-renderer"
>;

export class RendererPluginRuntimeV2 {
  private readonly reconciler: PluginSnapshotReconcilerV2;

  constructor(
    target: RendererDataPlaneTargetV2,
    definitions: Iterable<PluginDefinitionV2>,
  ) {
    this.reconciler = new PluginSnapshotReconcilerV2(
      new LoaderV2(definitions, target),
    );
  }

  readonly subscribe = (listener: () => void): (() => void) =>
    this.reconciler.manager.subscribe(listener);

  readonly getSnapshot = (): RuntimeGenerationV2 | undefined =>
    this.reconciler.manager.getSnapshot();

  async bootstrap(value: unknown): Promise<void> {
    const snapshot = await parseProfileSnapshotV2(value);
    await this.reconciler.bootstrap(snapshot);
  }

  async apply(value: unknown): Promise<SnapshotApplyReceiptV2> {
    const distribution = await parseControlPlaneDistributionV2(value);
    return this.reconciler.apply(distribution);
  }

  async close(): Promise<void> {
    await this.reconciler.close();
  }
}
