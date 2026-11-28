import type { DesktopWorkbenchTabBarInputV2 } from './DesktopWorkbenchTabBarSurfaceV2';
import { projectDesktopWorkbenchTabBarCompositionV2 } from './desktopRendererCompositionPortV2';
import { useDesktopRendererGenerationV2 } from './desktopRendererGenerationContextV2';

export interface DesktopRendererWorkbenchTabBarV2Props {
  readonly input: DesktopWorkbenchTabBarInputV2;
}

export function DesktopRendererWorkbenchTabBarV2({
  input,
}: DesktopRendererWorkbenchTabBarV2Props) {
  const { composition: compositionPort, state } = useDesktopRendererGenerationV2();
  const composition = projectDesktopWorkbenchTabBarCompositionV2(
    state.authority,
    compositionPort,
  );
  if (composition.status === 'ready') {
    const Surface = composition.Surface;
    return <Surface input={input} />;
  }
  return (
    <div
      className="workbench-tab-bar"
      data-workbench-tab-bar-state={composition.status}
      data-reason-code={
        composition.status === 'unavailable' ? composition.reasonCode : undefined
      }
      aria-hidden="true"
    />
  );
}
