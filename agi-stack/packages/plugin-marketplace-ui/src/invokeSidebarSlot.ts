import type { SidebarBinding, SidebarBindings, SidebarSlot } from '../../plugin-slots/src/sidebar';
import type { MarketplaceTransport } from './client';
import { packageBase, packageScope } from './pluginMarketTypes';

type Values = Record<string, unknown>;
export interface SidebarOwner {
  plugin: string;
  digest: string;
  projectId?: string;
  commands?: readonly string[];
  sidebar?: SidebarBindings;
}

export async function invokeSlot(
  transport: MarketplaceTransport,
  tenant: string,
  project: string,
  owner: SidebarOwner | undefined,
  slot: SidebarSlot,
  context: Values,
  signal: AbortSignal
) {
  const binding = owner?.sidebar?.[slot];
  if (
    !owner ||
    !binding ||
    !owner.commands?.includes(binding.command) ||
    owner.projectId !== project ||
    !tenant ||
    signal.aborted
  )
    throw new Error('package_command_unavailable');
  const values = { ...context, tenant, project, inactive: false };
  const payload = { ...binding.constants, ...mapFields(binding.inputs, values) };
  const result = await transport<Values>(
    packageBase(project) + '/' + encodeURIComponent(owner.plugin) + '/commands',
    {
      method: 'POST',
      signal,
      body: {
        ...packageScope(tenant, project),
        expected_digest: owner.digest,
        command_id: binding.command,
        payload,
      },
    }
  );
  signal.throwIfAborted();
  const raw = binding.collection ? result[binding.collection] : [result];
  if (!Array.isArray(raw)) throw new Error('invalid_sidebar_result');
  const rows = raw.flatMap((record: unknown) => {
    if (!record || typeof record !== 'object') return [];
    const item = record as Values;
    if (
      !Object.entries(binding.match ?? {}).every(
        ([key, source]) => Object.hasOwn(item, key) && item[key] === (values as Values)[source]
      )
    )
      return [];
    return [mapFields(binding.fields, item)];
  });
  return { rows, count: raw.length };
}
function mapFields(mapping: SidebarBinding['fields'], values: Values) {
  return Object.fromEntries(
    Object.entries(mapping ?? {}).flatMap(([dest, source]) =>
      Object.hasOwn(values, source) ? [[dest, values[source]]] : []
    )
  ) as Values;
}
