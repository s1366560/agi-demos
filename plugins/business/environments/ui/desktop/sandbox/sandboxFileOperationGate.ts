export type SandboxFileOperation = Readonly<{
  signal: AbortSignal;
  isCurrent(): boolean;
  finish(): void;
}>;

export type SandboxFileOperationGate = Readonly<{
  begin(): SandboxFileOperation;
  invalidate(): void;
}>;

export function createSandboxFileOperationGate(): SandboxFileOperationGate {
  let generation = 0;
  const controllers = new Set<AbortController>();

  return Object.freeze({
    begin(): SandboxFileOperation {
      const operationGeneration = generation;
      const controller = new AbortController();
      controllers.add(controller);
      return Object.freeze({
        signal: controller.signal,
        isCurrent: () =>
          generation === operationGeneration && !controller.signal.aborted,
        finish: () => {
          controllers.delete(controller);
        },
      });
    },
    invalidate(): void {
      generation += 1;
      for (const controller of controllers) controller.abort();
      controllers.clear();
    },
  });
}
