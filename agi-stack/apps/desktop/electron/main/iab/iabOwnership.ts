/** Trusted bridge scopes; never populated from browser pages or REPL arguments. */
export type BrowserCaller = Readonly<{
  sessionId: string;
  mainSessionId: string;
  callerId: string;
  turnId: string;
  allowDot: boolean;
}>;
export type BrowserSurface = 'iab' | 'dot';
type Claim = Readonly<{ callerId: string; turnId: string }>;
type OwnedTab = {
  sessionId: string;
  origin: 'agent' | 'user';
  claim?: Claim;
  mark?: 'handoff' | 'deliverable';
  interrupted: Set<string>;
};

export function browserCaller(params: unknown): BrowserCaller {
  const value = (params as { _browserCaller?: BrowserCaller } | null)?._browserCaller;
  if (!value || ['sessionId', 'mainSessionId', 'callerId', 'turnId'].some(key => {
    const field = value[key as keyof BrowserCaller];
    return typeof field !== 'string' || !field || field.length > 512;
  }) || typeof value.allowDot !== 'boolean') throw new Error('browser caller scope is required');
  return Object.freeze({ ...value });
}

export function browserSurface(params: unknown): BrowserSurface {
  const surface = (params as { _browserSurface?: string } | null)?._browserSurface ?? 'iab';
  if (surface !== 'iab' && surface !== 'dot') throw new Error('invalid browser surface');
  return surface;
}

export class IabOwnership {
  readonly #tabs = new Map<number, OwnedTab>();
  #activeSession: string | null = null;

  #session(caller: BrowserCaller, surface: BrowserSurface): string {
    if (surface === 'dot' && !caller.allowDot) throw new Error('Dot is not available to this caller');
    return surface === 'dot' ? caller.mainSessionId : caller.sessionId;
  }

  observe(caller: BrowserCaller, surface: BrowserSurface = 'iab'): void {
    // Agent activity never changes the user's selected conversation.
    this.#session(caller, surface);
  }

  activateSession(sessionId: string | null): void { this.#activeSession = sessionId; }

  sessionId(caller: BrowserCaller, surface: BrowserSurface): string { return this.#session(caller, surface); }

  get activeSession(): string | null { return this.#activeSession; }

  created(tabId: number, caller: BrowserCaller | null, origin: 'agent' | 'user', surface: BrowserSurface = 'iab'): void {
    const sessionId = caller ? this.#session(caller, surface) : this.#activeSession ?? 'desktop';
    this.#tabs.set(tabId, { sessionId, origin, interrupted: new Set(),
      ...(caller && origin === 'agent' ? { claim: { callerId: caller.callerId, turnId: caller.turnId } } : {}) });
  }

  createdFrom(tabId: number, parentId: number): void {
    const parent = this.#tabs.get(parentId);
    if (!parent) throw new Error('popup parent is unavailable');
    this.#tabs.set(tabId, { sessionId: parent.sessionId, origin: parent.claim ? 'agent' : 'user',
      claim: parent.claim, interrupted: new Set(parent.interrupted) });
  }

  list(caller: BrowserCaller, surface: BrowserSurface, includeUserTabs: boolean): number[] {
    this.observe(caller);
    const session = this.#session(caller, surface);
    return [...this.#tabs].filter(([, tab]) => tab.sessionId === session
      && (includeUserTabs || (tab.claim?.callerId === caller.callerId && tab.claim.turnId === caller.turnId)))
      .map(([id]) => id);
  }

  claim(tabId: number, caller: BrowserCaller, surface: BrowserSurface): void {
    const tab = this.#tabs.get(tabId);
    if (!tab || tab.sessionId !== this.#session(caller, surface)) throw new Error('tab is outside the browser scope');
    if (tab.interrupted.has(caller.turnId)) throw new Error('Browser use stopped because the user took control.');
    if (tab.claim && (tab.claim.callerId !== caller.callerId || tab.claim.turnId !== caller.turnId))
      throw new Error('tab is claimed by another caller');
    if (!tab.claim) tab.mark = undefined;
    tab.claim = { callerId: caller.callerId, turnId: caller.turnId };
  }

  mark(tabId: number, caller: BrowserCaller, surface: BrowserSurface, mark: 'handoff' | 'deliverable'): void {
    this.claim(tabId, caller, surface);
    this.#tabs.get(tabId)!.mark = mark;
  }

  takeOver(tabId: number): void {
    const tab = this.#tabs.get(tabId);
    if (!tab) throw new Error('tab is unavailable');
    if (tab.claim) tab.interrupted.add(tab.claim.turnId);
    tab.claim = undefined;
    // User explicitly retained this tab by taking control.
    tab.origin = 'user';
    tab.mark = undefined;
  }

  metadata(tabId: number) {
    const tab = this.#tabs.get(tabId);
    return tab ? { sessionId: tab.sessionId, origin: tab.origin,
      controller: tab.claim ? 'agent' as const : 'user' as const,
      callerId: tab.claim?.callerId ?? null, mark: tab.mark ?? null } : undefined;
  }

  finishTurn(turnId: string): number[] {
    const closed: number[] = [];
    for (const [id, tab] of this.#tabs) {
      tab.interrupted.delete(turnId);
      if (tab.claim?.turnId !== turnId) continue;
      if (tab.origin === 'agent' && !tab.mark) { closed.push(id); this.#tabs.delete(id); }
      else tab.claim = undefined;
    }
    return closed;
  }

  disconnect(): number[] {
    const turns = new Set([...this.#tabs.values()].flatMap(tab => tab.claim ? [tab.claim.turnId] : []));
    return [...turns].flatMap(turn => this.finishTurn(turn));
  }

  remove(tabId: number): void { this.#tabs.delete(tabId); }
}
