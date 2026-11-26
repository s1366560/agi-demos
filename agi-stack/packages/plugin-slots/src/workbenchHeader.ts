/**
 * Original workbench header shared by the cloud console and the desktop shell.
 * Section order is the original workbench's identity order. Groups follow the
 * first installed section of each group. Callers supply the slots their host
 * can open; this module only places installed pages onto those slots.
 */

export interface WorkbenchHeaderLink {
  readonly id: string;
  readonly label: string;
  readonly path: string;
  readonly paths?: readonly string[];
  readonly projectId?: string;
}

export interface WorkbenchHeaderSlot {
  readonly id: string;
  readonly label: string;
  readonly path: string;
  readonly context: string;
  readonly displayRole: string;
  readonly groupId?: string | undefined;
  readonly groupLabel?: string | undefined;
  readonly relativePath: string;
  readonly routeFamily: string;
  readonly exact?: boolean | undefined;
}

export type WorkbenchHeaderContext = "tenant" | "project" | "agent";

export const ORIGINAL_HEADER_ORDER: Record<
  "tenant" | "project",
  readonly string[]
> = {
  tenant: [
    "acp",
    "agent-bindings",
    "agent-definitions",
    "agent-workspace",
    "agent-configuration",
    "analytics",
    "audit-logs",
    "billing",
    "clusters",
    "dead-letter-queue",
    "decision-records",
    "deploy",
    "events",
    "evolution",
    "genes",
    "instance-templates",
    "instances",
    "mcp-servers",
    "org-settings",
    "overview",
    "patterns",
    "plugins",
    "pool",
    "projects",
    "providers",
    "runtimes",
    "settings",
    "skills",
    "tasks",
    "templates",
    "trust-policies",
    "users",
    "webhooks",
    "workspaces",
  ],
  project: [
    "blackboard",
    "channels",
    "communities",
    "cron-jobs",
    "entities",
    "graph",
    "maintenance",
    "memories",
    "overview",
    "schema",
    "search",
    "settings",
    "team",
    "workspaces",
  ],
};

const withoutSearch = (path: string) => path.split("?")[0] ?? path;

/** Address that owns a section and the pages nested below it. */
export function sectionRoot(slot: WorkbenchHeaderSlot): string | null {
  const path = withoutSearch(slot.path);
  const segment = slot.relativePath.split("/").filter(Boolean)[0];
  // The index section owns the whole scope, so it cannot adopt sibling pages.
  if (!segment) return null;
  const scope = path.slice(0, Math.max(0, path.length - slot.relativePath.length));
  return `${scope.replace(/\/$/, "")}/${segment}`;
}

/** Original menu positions apply only to entries the active installation exposes. */
export function layoutWorkbenchHeader<T extends WorkbenchHeaderSlot>(
  items: readonly WorkbenchHeaderLink[],
  original: readonly T[],
  context: WorkbenchHeaderContext,
): T[] {
  const projectHeader = context === "project";
  const order = context === "agent" ? [] : ORIGINAL_HEADER_ORDER[context];
  const rank = new Map(order.map((id, index) => [id, index]));
  const unranked = original.length;
  const position = (id: string) => rank.get(id) ?? unranked;
  const ranked = [...original].sort((a, b) => position(a.id) - position(b.id));
  // Groups keep the order of their first section in the original workbench, whichever
  // sections the active installation exposes.
  const groupRank = new Map<string, number>();
  for (const slot of ranked) {
    const group = slot.groupId ?? "ungrouped";
    if (!groupRank.has(group)) groupRank.set(group, groupRank.size);
  }
  const groupPosition = (item: WorkbenchHeaderSlot) =>
    groupRank.get(item.groupId ?? "ungrouped") ?? groupRank.size;
  // A project header lists project pages. A tenant header lists tenant pages and the
  // project pages its own sections open.
  const candidates = projectHeader ? items.filter((item) => item.projectId) : items;
  const addresses = (item: WorkbenchHeaderLink) =>
    (item.paths ?? [item.path]).map(withoutSearch);
  const byAddress = new Map<string, WorkbenchHeaderLink>();
  for (const item of candidates)
    for (const address of addresses(item))
      if (!byAddress.has(address)) byAddress.set(address, item);
  const placed = new Set<string>();
  const sections: string[] = [];
  const result: T[] = [];
  for (const slot of ranked) {
    const section = withoutSearch(slot.path);
    const item = byAddress.get(section);
    if (!item || placed.has(item.id)) continue;
    placed.add(item.id);
    const root = sectionRoot(slot);
    if (root) sections.push(root);
    result.push({
      ...slot,
      path: addresses(item).includes(section)
        ? ((item.paths ?? [item.path]).find((path) => withoutSearch(path) === section) ??
          item.path)
        : item.path,
    });
  }
  for (const item of candidates) {
    if (placed.has(item.id)) continue;
    // A page below an installed section belongs to that section, like creating an instance.
    if (
      addresses(item).some((address) =>
        sections.some((section) => address.startsWith(section + "/")),
      )
    )
      continue;
    if (!projectHeader && item.projectId) continue;
    placed.add(item.id);
    result.push({
      ...item,
      context,
      displayRole: "top-nav",
      relativePath: item.path,
      routeFamily: "tenant",
      groupId: "tenant-extensions-integrations",
      groupLabel: "nav.extensionsIntegrations",
    } as T);
  }
  return result.sort(
    (a, b) => groupPosition(a) - groupPosition(b) || position(a.id) - position(b.id),
  );
}

export function groupWorkbenchHeader<T extends { readonly id: string; readonly groupId?: string }>(
  items: readonly T[],
): { id: string; items: T[] }[] {
  const groups: { id: string; items: T[] }[] = [];
  for (const item of items) {
    const id = item.groupId ?? "ungrouped";
    const found = groups.find((group) => group.id === id);
    if (found) found.items.push(item);
    else groups.push({ id, items: [item] });
  }
  return groups;
}
