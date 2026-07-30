export type DesktopRouteScope = 'tenant' | 'project' | 'workspace' | 'instance';

export type DesktopRouteLocalPolicy =
  | 'native_equivalent'
  | 'cloud_only'
  | 'blocked_by_web_contract';

export type DesktopRouteLoader<TModule = unknown> = () => Promise<TModule>;

export type DesktopRouteDefinition<TModule = unknown> = Readonly<{
  id: string;
  path: string;
  scope: readonly DesktopRouteScope[];
  navGroup: string;
  capability: string;
  requiredPermission: string | null;
  localPolicy: DesktopRouteLocalPolicy;
  loader: DesktopRouteLoader<TModule>;
}>;

export type DesktopRouteContext = Readonly<{
  tenantId?: string;
  projectId?: string;
  workspaceId?: string;
  instanceId?: string;
}>;

export type DesktopRouteContextValidation =
  | Readonly<{
      valid: true;
      context: DesktopRouteContext;
    }>
  | Readonly<{
      valid: false;
      reasonCode: 'desktop_route_context_missing' | 'desktop_route_context_invalid';
      scope: DesktopRouteScope;
    }>;

export type DesktopRouteMatch<TModule = unknown> = Readonly<{
  definition: DesktopRouteDefinition<TModule>;
  context: DesktopRouteContext;
  canonicalPath: string;
}>;

export type DesktopRouteRestoreResult<TModule = unknown> =
  | Readonly<{
      status: 'matched';
      match: DesktopRouteMatch<TModule>;
    }>
  | Readonly<{
      status: 'not_found';
      reasonCode: 'desktop_route_malformed' | 'desktop_route_not_found';
    }>;

export type DesktopRouteRegistry<TModule = unknown> = Readonly<{
  definitions: readonly DesktopRouteDefinition<TModule>[];
  byId: ReadonlyMap<string, DesktopRouteDefinition<TModule>>;
}>;

const SCOPE_CONTEXT_KEYS = {
  tenant: 'tenantId',
  project: 'projectId',
  workspace: 'workspaceId',
  instance: 'instanceId',
} as const satisfies Record<DesktopRouteScope, keyof DesktopRouteContext>;

const SCOPE_PARAMETERS = {
  tenant: 'tenantId',
  project: 'projectId',
  workspace: 'workspaceId',
  instance: 'instanceId',
} as const satisfies Record<DesktopRouteScope, string>;

const SUPPORTED_LOCAL_POLICIES = new Set<DesktopRouteLocalPolicy>([
  'native_equivalent',
  'cloud_only',
  'blocked_by_web_contract',
]);

const SUPPORTED_SCOPE_PATHS: readonly (readonly DesktopRouteScope[])[] = [
  [],
  ['tenant'],
  ['tenant', 'project'],
  ['tenant', 'project', 'workspace'],
  ['tenant', 'instance'],
];

type ParsedLocation =
  | Readonly<{ valid: true; segments: readonly string[] }>
  | Readonly<{ valid: false }>;

export function createDesktopRouteRegistry<TModule>(
  definitions: readonly DesktopRouteDefinition<TModule>[],
): DesktopRouteRegistry<TModule> {
  const byId = new Map<string, DesktopRouteDefinition<TModule>>();
  const paths = new Set<string>();
  const normalized = definitions.map((definition) => {
    assertDesktopRouteDefinition(definition);
    if (byId.has(definition.id)) {
      throw new Error(`duplicate route id: ${definition.id}`);
    }
    if (paths.has(definition.path)) {
      throw new Error(`duplicate route path: ${definition.path}`);
    }
    const route = freezeDefinition(definition);
    byId.set(route.id, route);
    paths.add(route.path);
    return route;
  });
  return Object.freeze({
    definitions: Object.freeze(normalized),
    byId: immutableRouteLookup(byId),
  });
}

export function validateDesktopRouteContext(
  definition: DesktopRouteDefinition,
  context: DesktopRouteContext,
): DesktopRouteContextValidation {
  const scopedContext: Partial<Record<keyof DesktopRouteContext, string>> = {};
  for (const scope of definition.scope) {
    const key = SCOPE_CONTEXT_KEYS[scope];
    const value = context[key];
    if (value === undefined) {
      return {
        valid: false,
        reasonCode: 'desktop_route_context_missing',
        scope,
      };
    }
    if (!validContextValue(value)) {
      return {
        valid: false,
        reasonCode: 'desktop_route_context_invalid',
        scope,
      };
    }
    scopedContext[key] = value.trim();
  }
  return {
    valid: true,
    context: scopedContext,
  };
}

export function buildDesktopRoutePath(
  definition: DesktopRouteDefinition,
  context: DesktopRouteContext,
): string {
  const validation = validateDesktopRouteContext(definition, context);
  if (!validation.valid) {
    throw new Error(`${validation.reasonCode}:${validation.scope}`);
  }
  const parameters = new Map<string, string>();
  for (const scope of definition.scope) {
    const key = SCOPE_CONTEXT_KEYS[scope];
    const value = validation.context[key];
    if (value !== undefined) parameters.set(SCOPE_PARAMETERS[scope], value);
  }
  return routeSegments(definition.path)
    .map((segment) => {
      if (!segment.startsWith(':')) return segment;
      const value = parameters.get(segment.slice(1));
      if (value === undefined) {
        throw new Error(`desktop_route_context_missing:${segment.slice(1)}`);
      }
      return encodeURIComponent(value);
    })
    .join('/');
}

export function matchDesktopRoute<TModule>(
  registry: DesktopRouteRegistry<TModule>,
  location: string,
): DesktopRouteMatch<TModule> | null {
  const parsed = parseDesktopRouteLocation(location);
  if (!parsed.valid) return null;
  for (const definition of registry.definitions) {
    const templateSegments = routeSegments(definition.path);
    if (templateSegments.length !== parsed.segments.length) continue;
    const context: Partial<Record<keyof DesktopRouteContext, string>> = {};
    let matches = true;
    for (let index = 0; index < templateSegments.length; index += 1) {
      const template = templateSegments[index];
      const value = parsed.segments[index];
      if (!template.startsWith(':')) {
        if (template !== value) matches = false;
        continue;
      }
      const scope = scopeForParameter(template.slice(1));
      if (!scope || !validContextValue(value)) {
        matches = false;
        continue;
      }
      context[SCOPE_CONTEXT_KEYS[scope]] = value.trim();
    }
    if (!matches) continue;
    const validation = validateDesktopRouteContext(definition, context);
    if (!validation.valid) continue;
    return Object.freeze({
      definition,
      context: validation.context,
      canonicalPath: buildDesktopRoutePath(definition, validation.context),
    });
  }
  return null;
}

export function restoreDesktopRoute<TModule>(
  registry: DesktopRouteRegistry<TModule>,
  deepLink: string,
): DesktopRouteRestoreResult<TModule> {
  const parsed = parseDesktopRouteLocation(deepLink);
  if (!parsed.valid) {
    return {
      status: 'not_found',
      reasonCode: 'desktop_route_malformed',
    };
  }
  const match = matchDesktopRoute(registry, parsed.segments.map(encodeURIComponent).join('/'));
  if (!match) {
    return {
      status: 'not_found',
      reasonCode: 'desktop_route_not_found',
    };
  }
  return { status: 'matched', match };
}

function assertDesktopRouteDefinition(definition: DesktopRouteDefinition): void {
  if (!nonEmptyString(definition.id)) throw new Error('route id must be non-empty');
  if (!nonEmptyString(definition.navGroup)) throw new Error('route navGroup must be non-empty');
  if (!nonEmptyString(definition.capability)) {
    throw new Error('route capability must be non-empty');
  }
  if (
    definition.requiredPermission !== null &&
    !nonEmptyString(definition.requiredPermission)
  ) {
    throw new Error('route requiredPermission must be non-empty or null');
  }
  if (!SUPPORTED_LOCAL_POLICIES.has(definition.localPolicy)) {
    throw new Error(`unsupported local policy: ${String(definition.localPolicy)}`);
  }
  if (typeof definition.loader !== 'function') throw new Error('route loader must be callable');
  if (!supportedScopePath(definition.scope)) {
    throw new Error(`unsupported route scope: ${definition.scope.join('/')}`);
  }
  const parameters = routeSegments(definition.path).flatMap((segment) => {
    if (!segment.startsWith(':')) return [];
    const parameter = segment.slice(1);
    if (!scopeForParameter(parameter)) {
      throw new Error(`unsupported route parameter: ${parameter}`);
    }
    return [parameter];
  });
  const expected = definition.scope.map((scope) => SCOPE_PARAMETERS[scope]);
  if (!sameValues(parameters, expected)) {
    throw new Error('route path parameters must match scope');
  }
}

function routeSegments(path: string): string[] {
  if (
    !path.startsWith('/') ||
    path === '/' ||
    path.endsWith('/') ||
    path.includes('?') ||
    path.includes('#')
  ) {
    throw new Error(`invalid route path: ${path}`);
  }
  const segments = path.split('/');
  if (segments.some((segment, index) => index > 0 && !segment)) {
    throw new Error(`invalid route path: ${path}`);
  }
  return segments;
}

function parseDesktopRouteLocation(location: string): ParsedLocation {
  if (typeof location !== 'string') return { valid: false };
  const trimmed = location.trim();
  if (!trimmed) return { valid: false };
  const hashIndex = trimmed.indexOf('#');
  const hashPath = hashIndex >= 0 ? trimmed.slice(hashIndex + 1) : trimmed;
  const path = hashPath.split('?', 1)[0];
  if (!path.startsWith('/')) return { valid: false };
  const canonicalInput = path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path;
  const rawSegments = canonicalInput.split('/');
  if (rawSegments.some((segment, index) => index > 0 && !segment)) {
    return { valid: false };
  }
  try {
    return {
      valid: true,
      segments: rawSegments.map((segment) => decodeURIComponent(segment)),
    };
  } catch {
    return { valid: false };
  }
}

function freezeDefinition<TModule>(
  definition: DesktopRouteDefinition<TModule>,
): DesktopRouteDefinition<TModule> {
  return Object.freeze({
    id: definition.id,
    path: definition.path,
    scope: Object.freeze([...definition.scope]),
    navGroup: definition.navGroup,
    capability: definition.capability,
    requiredPermission: definition.requiredPermission,
    localPolicy: definition.localPolicy,
    loader: definition.loader,
  });
}

function scopeForParameter(parameter: string): DesktopRouteScope | null {
  for (const scope of Object.keys(SCOPE_PARAMETERS) as DesktopRouteScope[]) {
    if (SCOPE_PARAMETERS[scope] === parameter) return scope;
  }
  return null;
}

function supportedScopePath(scope: readonly DesktopRouteScope[]): boolean {
  return SUPPORTED_SCOPE_PATHS.some((candidate) => sameValues(candidate, scope));
}

function sameValues(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function validContextValue(value: unknown): value is string {
  if (!nonEmptyString(value)) return false;
  const normalized = value.trim();
  if (normalized === '.' || normalized === '..') return false;
  return [...normalized].every((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint >= 0x20 && codePoint !== 0x7f;
  });
}

function immutableRouteLookup<TKey, TValue>(
  source: ReadonlyMap<TKey, TValue>,
): ReadonlyMap<TKey, TValue> {
  let lookup: ReadonlyMap<TKey, TValue>;
  lookup = Object.freeze({
    get size() {
      return source.size;
    },
    get(key: TKey) {
      return source.get(key);
    },
    has(key: TKey) {
      return source.has(key);
    },
    entries() {
      return source.entries();
    },
    keys() {
      return source.keys();
    },
    values() {
      return source.values();
    },
    forEach(
      callback: (value: TValue, key: TKey, map: ReadonlyMap<TKey, TValue>) => void,
      thisArg?: unknown,
    ) {
      source.forEach((value, key) => callback.call(thisArg, value, key, lookup));
    },
    [Symbol.iterator]() {
      return source[Symbol.iterator]();
    },
  });
  return lookup;
}
