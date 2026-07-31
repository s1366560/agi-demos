export interface TenantProjectsDialogFocusTarget {
  readonly isConnected: boolean;
  focus(): void;
}

export function restoreTenantProjectsDialogFocus({
  trigger,
  fallback,
  schedule = (callback) => window.requestAnimationFrame(callback),
}: Readonly<{
  trigger: TenantProjectsDialogFocusTarget | null;
  fallback: TenantProjectsDialogFocusTarget | null;
  schedule?: (callback: () => void) => void;
}>): void {
  schedule(() => {
    const target = trigger?.isConnected ? trigger : fallback?.isConnected ? fallback : null;
    target?.focus();
  });
}
