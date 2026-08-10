/**
 * iab tab identity: iab-local integer tabIds plus the no-op tab-group model.
 *
 * The bridge contract namespaces tabIds per backend, so iab uses a plain
 * incrementing counter (never reused within a session). Tab groups are
 * tracked as pure membership records — the M4 iab tab strip does not render
 * group chrome, so `ensureTabGroup`/`assignTab`/`ungroupTab` only maintain
 * the bookkeeping `turnEnded` needs (ungroup counts). Pure module, no
 * Electron imports, unit-tested from the compiled dist.
 */

export type IabTabRecord = Readonly<{
  tabId: number;
  groupId: number | null;
}>;

export type IabTurnEndedLease = Readonly<{
  tabId: number;
  origin: 'agent' | 'user';
  mark: 'handoff' | 'deliverable' | null;
}>;

export type IabTurnEndedPlan = Readonly<{
  /** Tabs turnEnded must close (agent-owned, unmarked). */
  closeTabIds: readonly number[];
  /** Tabs turnEnded must keep but ungroup. */
  ungroupTabIds: readonly number[];
  /** Lease tabIds that do not resolve to a live tab. */
  unknownTabIds: readonly number[];
}>;

export class IabTabRegistry {
  #nextTabId = 1;
  #nextGroupId = 1;
  readonly #tabs = new Map<number, { groupId: number | null }>();
  readonly #groupsByKey = new Map<string, number>();

  createTab(): number {
    const tabId = this.#nextTabId;
    this.#nextTabId += 1;
    this.#tabs.set(tabId, { groupId: null });
    return tabId;
  }

  hasTab(tabId: number): boolean {
    return this.#tabs.has(tabId);
  }

  removeTab(tabId: number): boolean {
    return this.#tabs.delete(tabId);
  }

  listTabIds(): number[] {
    return [...this.#tabs.keys()];
  }

  tabGroupId(tabId: number): number | null {
    return this.#tabs.get(tabId)?.groupId ?? null;
  }

  /** Idempotent per `key`: one group per agent run. */
  ensureTabGroup(key: string): number {
    const existing = this.#groupsByKey.get(key);
    if (existing !== undefined) return existing;
    const groupId = this.#nextGroupId;
    this.#nextGroupId += 1;
    this.#groupsByKey.set(key, groupId);
    return groupId;
  }

  assignTab(tabId: number, groupId: number): void {
    const tab = this.#tabs.get(tabId);
    if (!tab) throw new Error(`iab tab ${tabId} does not exist`);
    if (![...this.#groupsByKey.values()].includes(groupId)) {
      throw new Error(`iab tab group ${groupId} does not exist`);
    }
    tab.groupId = groupId;
  }

  ungroupTab(tabId: number): boolean {
    const tab = this.#tabs.get(tabId);
    if (!tab) throw new Error(`iab tab ${tabId} does not exist`);
    const wasGrouped = tab.groupId !== null;
    tab.groupId = null;
    return wasGrouped;
  }

  /**
   * End-of-turn disposition (bridge `turnEnded`): agent-owned leases without
   * a mark are closed; marked leases (handoff/deliverable) and user-owned
   * leases are kept and ungrouped.
   */
  planTurnEnded(leases: readonly IabTurnEndedLease[]): IabTurnEndedPlan {
    const closeTabIds: number[] = [];
    const ungroupTabIds: number[] = [];
    const unknownTabIds: number[] = [];
    const seen = new Set<number>();
    for (const lease of leases) {
      if (seen.has(lease.tabId)) continue;
      seen.add(lease.tabId);
      if (!this.#tabs.has(lease.tabId)) {
        unknownTabIds.push(lease.tabId);
        continue;
      }
      if (lease.origin === 'agent' && lease.mark === null) {
        closeTabIds.push(lease.tabId);
      } else if (this.tabGroupId(lease.tabId) !== null) {
        ungroupTabIds.push(lease.tabId);
      }
    }
    return Object.freeze({
      closeTabIds: Object.freeze(closeTabIds),
      ungroupTabIds: Object.freeze(ungroupTabIds),
      unknownTabIds: Object.freeze(unknownTabIds),
    });
  }
}
