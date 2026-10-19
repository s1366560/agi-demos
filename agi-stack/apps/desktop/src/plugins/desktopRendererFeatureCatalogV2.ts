import type { DesktopRendererArtifactV2 } from './desktopRendererArtifactCatalogV2';
import { SETTINGS_GROUPS } from '../features/settings/settingsNavigationModel';
import { KEYBOARD_SHORTCUTS } from '../features/navigation/keyboardShortcutModel';

export interface DesktopRendererFeatureV2 {
  readonly id: string;
  readonly contributions: readonly {
    readonly kind: DesktopRendererArtifactV2['kind'];
    readonly artifactRef: string;
  }[];
  readonly permissions: readonly string[];
}

export const DESKTOP_SHELL_COMMAND_IDS_V2 = Object.freeze([
  'home',
  'my-work',
  'activity',
  'settings',
  'browser-integration-settings',
  'sign-in',
  'refresh-runtime',
  'keyboard-shortcuts',
]);
export const DESKTOP_WORK_PANEL_IDS_V2 = Object.freeze([
  'plan',
  'changes',
  'artifacts',
  'terminal',
  'checks',
  'verification',
  'sources',
  'browser',
  'run-details',
  'apps',
  'overview',
  'activity',
  'agents',
  'graph',
  'insights',
  'context',
  'runtime',
]);

/** Build leaf contributions from the trusted composition definitions, preserving route factories. */
export function registerDesktopFeatureArtifactsV2(
  catalog: Map<string, DesktopRendererArtifactV2>,
): readonly DesktopRendererFeatureV2[] {
  const features: DesktopRendererFeatureV2[] = [];
  const originals = [...catalog.values()];
  for (const route of originals) {
    if (route.kind !== 'route') continue;
    for (const routeId of route.routeIds) {
      const routeRef = `desktop.routes.feature.${routeId}.v1`;
      catalog.set(
        routeRef,
        Object.freeze({
          id: routeRef,
          kind: 'route',
          compositionArtifactId: route.id,
          routeIds: Object.freeze([routeId]),
        }),
      );
      const contributions: DesktopRendererFeatureV2['contributions'][number][] = [
        { kind: 'route', artifactRef: routeRef },
      ];
      const navigation = originals.find(
        (artifact) => artifact.kind === 'navigation' && artifact.routeIds.includes(routeId),
      );
      if (navigation?.kind === 'navigation') {
        const navRef = `desktop.navigation.feature.${routeId}.v1`;
        catalog.set(
          navRef,
          Object.freeze({
            id: navRef,
            kind: 'navigation',
            routeIds: Object.freeze([routeId]),
            discoveryRouteIds: Object.freeze(
              navigation.discoveryRouteIds.includes(routeId) ? [routeId] : [],
            ),
          }),
        );
        contributions.push({ kind: 'navigation', artifactRef: navRef });
      }
      features.push(
        Object.freeze({
          id: `desktop.feature.${routeId}`,
          contributions: Object.freeze(contributions),
          permissions: [],
        }),
      );
    }
  }
  for (const sectionId of [...SETTINGS_GROUPS.flatMap((group) => group.sections), 'connection']) {
    const ref = `desktop.settings.${sectionId}.v1`;
    catalog.set(
      ref,
      Object.freeze({ id: ref, kind: 'settings-page', sectionIds: Object.freeze([sectionId]) }),
    );
    features.push({
      id: `desktop.settings.${sectionId}`,
      contributions: [{ kind: 'settings-page', artifactRef: ref }],
      permissions: [],
    });
  }
  for (const commandId of DESKTOP_SHELL_COMMAND_IDS_V2) {
    const ref = `desktop.commands.${commandId}.v1`;
    catalog.set(
      ref,
      Object.freeze({
        id: ref,
        kind: 'command',
        commandIds: Object.freeze([commandId]),
        shortcutIds: [],
      }),
    );
    features.push({
      id: `desktop.command.${commandId}`,
      contributions: [{ kind: 'command', artifactRef: ref }],
      permissions: [],
    });
  }
  for (const shortcut of KEYBOARD_SHORTCUTS) {
    const ref = `desktop.shortcuts.${shortcut.id}.v1`;
    catalog.set(
      ref,
      Object.freeze({
        id: ref,
        kind: 'command',
        commandIds: [],
        shortcutIds: Object.freeze([shortcut.id]),
      }),
    );
    features.push({
      id: `desktop.shortcut.${shortcut.id}`,
      contributions: [{ kind: 'command', artifactRef: ref }],
      permissions: [],
    });
  }
  for (const panelId of DESKTOP_WORK_PANEL_IDS_V2) {
    const ref = `desktop.ui-slots.panel.${panelId}.v1`;
    catalog.set(
      ref,
      Object.freeze({
        id: ref,
        kind: 'ui-slot',
        slotDefinitions: Object.freeze([
          {
            id: panelId,
            pluginId: 'builtin-shell',
            slot: 'work_panel' as const,
            contract: `ui-builtin:desktop-work-panel:${panelId}`,
            moduleRef: `builtin:desktop-work-panel:${panelId}`,
            permission: 'ui.work-panel',
            sandbox: true,
          },
        ]),
      }),
    );
    features.push({
      id: `desktop.panel.${panelId}`,
      contributions: [{ kind: 'ui-slot', artifactRef: ref }],
      permissions: ['ui.work-panel'],
    });
  }
  return Object.freeze(features);
}
