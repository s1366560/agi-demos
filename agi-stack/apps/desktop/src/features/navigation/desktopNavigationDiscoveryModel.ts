import {
  CANONICAL_DESKTOP_NAVIGATION_GROUPS,
  CANONICAL_DESKTOP_NAVIGATION_METADATA,
  type DesktopNavigationIconKey,
} from './desktopCanonicalNavigationCatalog';
import type { CanonicalDesktopRouteId } from './desktopCanonicalRouteCatalog';
import {
  buildDesktopRoutePath,
  type DesktopRouteContext,
  type DesktopRouteDefinition,
  type DesktopRouteRegistry,
  type DesktopRouteScope,
  validateDesktopRouteContext,
} from './desktopRouteRegistry';

type DesktopNavigationTranslator = (
  key: string,
  values?: Readonly<Record<string, string | number>>,
) => string;

export type DesktopNavigationDisabledReason = Readonly<{
  code:
    | 'desktop_navigation_authentication_required'
    | 'desktop_route_context_missing'
    | 'desktop_route_context_invalid';
  scope: DesktopRouteScope | null;
}>;

export type DesktopNavigationDiscoveryEntry<TModule = unknown> = Readonly<{
  routeId: CanonicalDesktopRouteId;
  definition: DesktopRouteDefinition<TModule>;
  destinationPath: string | null;
  groupId: string;
  groupLabelKey: string;
  groupLabel: string;
  labelKey: string;
  label: string;
  descriptionKey: string;
  description: string;
  displayRole: 'top-nav' | 'overflow';
  iconKey: DesktopNavigationIconKey;
  aliases: readonly string[];
  disabledReason: DesktopNavigationDisabledReason | null;
  searchText: string;
}>;

export type DesktopNavigationDiscoveryGroup<TModule = unknown> = Readonly<{
  id: string;
  labelKey: string;
  label: string;
  iconKey: DesktopNavigationIconKey;
  entries: readonly DesktopNavigationDiscoveryEntry<TModule>[];
}>;

export function deriveDesktopNavigationDiscoveryEntries<TModule>({
  registry,
  authenticated,
  context,
  translate,
}: Readonly<{
  registry: DesktopRouteRegistry<TModule>;
  authenticated: boolean;
  context: DesktopRouteContext;
  translate: DesktopNavigationTranslator;
}>): readonly DesktopNavigationDiscoveryEntry<TModule>[] {
  const groups = new Map<string, (typeof CANONICAL_DESKTOP_NAVIGATION_GROUPS)[number]>(
    CANONICAL_DESKTOP_NAVIGATION_GROUPS.map((group) => [group.id, group]),
  );
  if (
    CANONICAL_DESKTOP_NAVIGATION_METADATA.length !== registry.definitions.length ||
    new Set(CANONICAL_DESKTOP_NAVIGATION_METADATA.map(({ routeId }) => routeId)).size !==
      CANONICAL_DESKTOP_NAVIGATION_METADATA.length
  ) {
    throw new Error('desktop_navigation_discovery_catalog_invalid');
  }

  return Object.freeze(
    CANONICAL_DESKTOP_NAVIGATION_METADATA.map((metadata) => {
      const definition = registry.byId.get(metadata.routeId);
      if (!definition) {
        throw new Error(`desktop_navigation_discovery_route_missing:${metadata.routeId}`);
      }
      const group = groups.get(definition.navGroup);
      if (!group) {
        throw new Error(`desktop_navigation_discovery_group_missing:${definition.navGroup}`);
      }
      const disabledReason = resolveDesktopNavigationDisabledReason(
        definition,
        authenticated,
        context,
      );
      const label = translate(metadata.labelKey);
      const groupLabel = translate(group.labelKey);
      const description = translate(metadata.descriptionKey, { label });
      const searchText = [
        label,
        description,
        groupLabel,
        definition.navGroup,
        metadata.routeId,
        ...metadata.aliases,
      ].join(' ');
      return Object.freeze({
        routeId: metadata.routeId,
        definition,
        destinationPath: disabledReason ? null : buildDesktopRoutePath(definition, context),
        groupId: definition.navGroup,
        groupLabelKey: group.labelKey,
        groupLabel,
        labelKey: metadata.labelKey,
        label,
        descriptionKey: metadata.descriptionKey,
        description,
        displayRole: metadata.displayRole,
        iconKey: group.iconKey,
        aliases: metadata.aliases,
        disabledReason,
        searchText,
      });
    }),
  );
}

export function deriveDesktopNavigationDiscoveryGroups<TModule>(
  entries: readonly DesktopNavigationDiscoveryEntry<TModule>[],
): readonly DesktopNavigationDiscoveryGroup<TModule>[] {
  return Object.freeze(
    CANONICAL_DESKTOP_NAVIGATION_GROUPS.flatMap((group) => {
      const groupEntries = entries.filter(({ groupId }) => groupId === group.id);
      if (groupEntries.length === 0) return [];
      return [
        Object.freeze({
          id: group.id,
          labelKey: group.labelKey,
          label: groupEntries[0].groupLabel,
          iconKey: group.iconKey,
          entries: Object.freeze(groupEntries),
        }),
      ];
    }),
  );
}

export function filterDesktopNavigationDiscoveryEntries<TModule>(
  entries: readonly DesktopNavigationDiscoveryEntry<TModule>[],
  query: string,
  locale: string,
): readonly DesktopNavigationDiscoveryEntry<TModule>[] {
  const normalized = query.trim().toLocaleLowerCase(locale);
  if (!normalized) return entries;
  return entries.filter(({ searchText }) =>
    searchText.toLocaleLowerCase(locale).includes(normalized),
  );
}

export function resolveDesktopNavigationDisabledReason(
  definition: DesktopRouteDefinition,
  authenticated: boolean,
  context: DesktopRouteContext,
): DesktopNavigationDisabledReason | null {
  if (
    !authenticated &&
    definition.requiredPermission.some((alternative) => alternative.includes('authenticated'))
  ) {
    return {
      code: 'desktop_navigation_authentication_required',
      scope: null,
    };
  }
  const validation = validateDesktopRouteContext(definition, context);
  if (!validation.valid) {
    return {
      code: validation.reasonCode,
      scope: validation.scope,
    };
  }
  return null;
}
