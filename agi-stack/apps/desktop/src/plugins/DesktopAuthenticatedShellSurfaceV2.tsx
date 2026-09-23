import { TitlebarToolbarProvider } from '../features/chat/ConversationToolbar';
import type { ComponentProps, CSSProperties, RefObject } from 'react';
import { Theme } from '@radix-ui/themes';

import type { ResolvedTheme } from '../theme';
import type { DesktopCommandPaletteInputV2 } from './DesktopCommandPaletteSurfaceV2';
import type { DesktopKeyboardShortcutsInputV2 } from './DesktopKeyboardShortcutsSurfaceV2';
import type { DesktopNewTaskFlowInputV2 } from './DesktopNewTaskFlowSurfaceV2';
import { DesktopRendererCommandPaletteV2 } from './DesktopRendererCommandPaletteV2';
import { DesktopRendererKeyboardShortcutsV2 } from './DesktopRendererKeyboardShortcutsV2';
import { DesktopRendererNewTaskFlowV2 } from './DesktopRendererNewTaskFlowV2';
import { DesktopRendererProductionRouterV2 } from './DesktopRendererProductionRouterV2';
import { DesktopRendererRightSidebarV2 } from './DesktopRendererRightSidebarV2';
import { DesktopRendererSettingsWindowV2 } from './DesktopRendererSettingsWindowV2';
import { DesktopRendererSidebarV2 } from './DesktopRendererSidebarV2';
import { DesktopRendererStatusBarV2 } from './DesktopRendererStatusBarV2';
import { DesktopRendererTitlebarV2 } from './DesktopRendererTitlebarV2';
import { DesktopRendererWorkspaceCreateV2 } from './DesktopRendererWorkspaceCreateV2';
import { DesktopRendererWorkspaceSettingsV2 } from './DesktopRendererWorkspaceSettingsV2';
import { DesktopRendererWorkbenchTabBarV2 } from './DesktopRendererWorkbenchTabBarV2';
import type { DesktopSettingsWindowInputV2 } from './DesktopSettingsWindowSurfaceV2';
import type { DesktopRightSidebarInputV2 } from './DesktopRightSidebarSurfaceV2';
import type { DesktopSidebarInputV2 } from './DesktopSidebarSurfaceV2';
import type { DesktopStatusBarInputV2 } from './DesktopStatusBarSurfaceV2';
import type { DesktopTitlebarInputV2 } from './DesktopTitlebarSurfaceV2';
import type { DesktopWorkspaceCreateInputV2 } from './DesktopWorkspaceCreateSurfaceV2';
import type { DesktopWorkspaceSettingsInputV2 } from './DesktopWorkspaceSettingsSurfaceV2';
import type { DesktopWorkbenchTabBarInputV2 } from './DesktopWorkbenchTabBarSurfaceV2';
import type { DesktopRendererGenerationMetaV2 } from './desktopRendererGenerationContextV2';

export type DesktopAuthenticatedShellOptionalOutletV2<Props> =
  | Readonly<{ kind: 'hidden' }>
  | Readonly<{ kind: 'visible'; props: Props }>;

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
    newTask: DesktopNewTaskFlowInputV2;
    rightSidebar: DesktopAuthenticatedShellOptionalOutletV2<DesktopRightSidebarInputV2>;
    router: ComponentProps<typeof DesktopRendererProductionRouterV2>;
    settings: DesktopSettingsWindowInputV2;
    sidebar: DesktopSidebarInputV2;
    statusBar: DesktopStatusBarInputV2;
    tabBar: DesktopWorkbenchTabBarInputV2;
    titlebar: DesktopTitlebarInputV2;
    workspaceCreate: DesktopWorkspaceCreateInputV2;
    workspaceSettings: DesktopWorkspaceSettingsInputV2;
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
  return (
    <TitlebarToolbarProvider>
      <Theme
        appearance={meta.appearance}
        accentColor="gray"
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
          <DesktopRendererTitlebarV2 input={surfaces.titlebar} />
          <section className="desktop-body">
            <DesktopRendererSidebarV2 input={surfaces.sidebar} />

            <main ref={meta.workbenchRef} className="workbench" tabIndex={-1}>
              <DesktopRendererWorkbenchTabBarV2 input={surfaces.tabBar} />
              <div className="workbench-content">
                <DesktopRendererProductionRouterV2 {...surfaces.router} />
              </div>
            </main>

            {surfaces.rightSidebar.kind === 'visible' ? (
              <DesktopRendererRightSidebarV2
                input={surfaces.rightSidebar.props}
              />
            ) : null}
          </section>

          <DesktopRendererStatusBarV2 input={surfaces.statusBar} />

          <DesktopRendererCommandPaletteV2 input={surfaces.commandPalette} />
          <DesktopRendererKeyboardShortcutsV2
            input={surfaces.keyboardShortcuts}
          />
          <DesktopRendererNewTaskFlowV2 input={surfaces.newTask} />
          <DesktopRendererWorkspaceCreateV2 input={surfaces.workspaceCreate} />
          <DesktopRendererWorkspaceSettingsV2
            input={surfaces.workspaceSettings}
          />
          <DesktopRendererSettingsWindowV2 input={surfaces.settings} />
        </div>
      </Theme>
    </TitlebarToolbarProvider>
  );
}
