import type { ComponentProps, CSSProperties, RefObject } from 'react';
import { Theme } from '@radix-ui/themes';

import { ResizeHandle } from '../components/ResizeHandle';
import { DesktopRightSidebar } from '../features/chrome/DesktopRightSidebar';
import { DesktopTitlebar } from '../features/chrome/DesktopTitlebar';
import { WorkbenchTabBar } from '../features/chrome/WorkbenchTabBar';
import { DesktopSidebar } from '../features/navigation/DesktopSidebar';
import { NewTaskFlow } from '../features/task/NewTaskFlow';
import { WorkspaceSettingsDialog } from '../features/workspace/WorkspaceSettingsDialog';
import type { ResolvedTheme } from '../theme';
import type { DesktopCommandPaletteInputV2 } from './DesktopCommandPaletteSurfaceV2';
import type { DesktopKeyboardShortcutsInputV2 } from './DesktopKeyboardShortcutsSurfaceV2';
import { DesktopRendererCommandPaletteV2 } from './DesktopRendererCommandPaletteV2';
import { DesktopRendererKeyboardShortcutsV2 } from './DesktopRendererKeyboardShortcutsV2';
import { DesktopRendererProductionRouterV2 } from './DesktopRendererProductionRouterV2';
import { DesktopRendererSettingsWindowV2 } from './DesktopRendererSettingsWindowV2';
import { DesktopRendererStatusBarV2 } from './DesktopRendererStatusBarV2';
import { DesktopRendererWorkspaceCreateV2 } from './DesktopRendererWorkspaceCreateV2';
import type { DesktopSettingsWindowInputV2 } from './DesktopSettingsWindowSurfaceV2';
import type { DesktopStatusBarInputV2 } from './DesktopStatusBarSurfaceV2';
import type { DesktopWorkspaceCreateInputV2 } from './DesktopWorkspaceCreateSurfaceV2';
import type { DesktopRendererGenerationMetaV2 } from './desktopRendererGenerationContextV2';

export type DesktopAuthenticatedShellOptionalOutletV2<Props> =
  | Readonly<{ kind: 'hidden' }>
  | Readonly<{ kind: 'visible'; props: Props }>;

type DesktopAuthenticatedShellSidebarV2 = Readonly<{
  props: Omit<ComponentProps<typeof DesktopSidebar>, 'resizeHandle'>;
  resizeHandle: DesktopAuthenticatedShellOptionalOutletV2<
    ComponentProps<typeof ResizeHandle>
  >;
}>;

export interface DesktopAuthenticatedShellViewModelV2 {
  readonly meta: Readonly<{
    appearance: ResolvedTheme;
    appShellRef: RefObject<HTMLDivElement | null>;
    generation: DesktopRendererGenerationMetaV2;
    workbenchRef: RefObject<HTMLElement | null>;
  }>;
  readonly state: Readonly<{
    layoutMode: 'default' | 'my-work';
    sidebarCollapsed: boolean;
    sidebarPreferredWidth: number;
    windowMode: 'browser' | 'native';
  }>;
  readonly surfaces: Readonly<{
    commandPalette: DesktopCommandPaletteInputV2;
    keyboardShortcuts: DesktopKeyboardShortcutsInputV2;
    newTask: ComponentProps<typeof NewTaskFlow>;
    rightSidebar: DesktopAuthenticatedShellOptionalOutletV2<
      ComponentProps<typeof DesktopRightSidebar>
    >;
    router: ComponentProps<typeof DesktopRendererProductionRouterV2>;
    settings: DesktopSettingsWindowInputV2;
    sidebar: DesktopAuthenticatedShellSidebarV2;
    statusBar: DesktopStatusBarInputV2;
    tabBar: ComponentProps<typeof WorkbenchTabBar>;
    titlebar: DesktopAuthenticatedShellOptionalOutletV2<
      ComponentProps<typeof DesktopTitlebar>
    >;
    workspaceCreate: DesktopWorkspaceCreateInputV2;
    workspaceSettings: ComponentProps<typeof WorkspaceSettingsDialog>;
  }>;
}

export function DesktopAuthenticatedShellSurfaceV2({
  viewModel,
}: Readonly<{ viewModel: DesktopAuthenticatedShellViewModelV2 }>) {
  const { meta, state, surfaces } = viewModel;
  const shellClassName = [
    'app-shell hierarchy-shell runtime-mode',
    state.windowMode === 'native' ? 'desktop-window' : 'browser-window',
    state.sidebarCollapsed ? 'sidebar-collapsed' : '',
    state.layoutMode === 'my-work' ? 'my-work-mode' : '',
  ]
    .filter(Boolean)
    .join(' ');
  const sidebarResizeHandle =
    surfaces.sidebar.resizeHandle.kind === 'visible' ? (
      <ResizeHandle {...surfaces.sidebar.resizeHandle.props} />
    ) : undefined;

  return (
    <Theme
      appearance={meta.appearance}
      accentColor="cyan"
      grayColor="slate"
      radius="medium"
      scaling="95%"
    >
      <div
        ref={meta.appShellRef}
        data-plugin-generation-v2={meta.generation.digest ?? 'unavailable'}
        data-plugin-generation-v2-status={meta.generation.status}
        data-plugin-generation-v2-target={meta.generation.target}
        className={shellClassName}
        style={
          {
            '--desktop-sidebar-preferred-width': `${Math.round(
              state.sidebarPreferredWidth,
            )}px`,
          } as CSSProperties
        }
      >
        {surfaces.titlebar.kind === 'visible' ? (
          <DesktopTitlebar {...surfaces.titlebar.props} />
        ) : null}
        <section className="desktop-body">
          <DesktopSidebar {...surfaces.sidebar.props} resizeHandle={sidebarResizeHandle} />

          <main ref={meta.workbenchRef} className="workbench" tabIndex={-1}>
            <WorkbenchTabBar {...surfaces.tabBar} />
            <div className="workbench-content">
              <DesktopRendererProductionRouterV2 {...surfaces.router} />
            </div>
          </main>

          {surfaces.rightSidebar.kind === 'visible' ? (
            <DesktopRightSidebar {...surfaces.rightSidebar.props} />
          ) : null}
        </section>

        <DesktopRendererStatusBarV2 input={surfaces.statusBar} />

        <DesktopRendererCommandPaletteV2 input={surfaces.commandPalette} />
        <DesktopRendererKeyboardShortcutsV2 input={surfaces.keyboardShortcuts} />
        <NewTaskFlow {...surfaces.newTask} />
        <DesktopRendererWorkspaceCreateV2 input={surfaces.workspaceCreate} />
        <WorkspaceSettingsDialog {...surfaces.workspaceSettings} />
        <DesktopRendererSettingsWindowV2 input={surfaces.settings} />
      </div>
    </Theme>
  );
}
