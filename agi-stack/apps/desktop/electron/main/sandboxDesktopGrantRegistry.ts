import {
  authorizeSandboxDesktopGrantRequest,
  createSandboxDesktopGrantPolicy,
  parseSandboxDesktopGrantClose,
  parseSandboxDesktopGrantOpen,
  sandboxDesktopGrantReply,
  type SandboxDesktopGrantOpen,
  type SandboxDesktopGrantPolicy,
  type SandboxDesktopGrantReply,
  type SandboxDesktopGrantRequestDetails,
} from './sandboxDesktopGrantPolicy';

export type SandboxDesktopGrantAuthorization = Readonly<{
  apiBaseUrl: string;
  credential: string;
  expiresAt?: string | null;
}>;
export type SandboxDesktopGrantRegistryDependencies = Readonly<{
  authorize(
    request: SandboxDesktopGrantOpen,
    signal: AbortSignal,
  ): Promise<SandboxDesktopGrantAuthorization>;
  randomId(): string;
  now?(): number;
  blankFrame(ownerId: number, frameTreeNodeId: number): Promise<void>;
  openTimeoutMs?: number;
}>;
export type SandboxDesktopGrantNetworkDetails = SandboxDesktopGrantRequestDetails &
  Readonly<{ id: number }>;
export type SandboxDesktopGrantHeaderDecision =
  | Readonly<{ kind: 'unrelated' }>
  | Readonly<{ kind: 'blocked' }>
  | Readonly<{ kind: 'authorized'; requestHeaders: Record<string, string> }>;
export type SandboxDesktopResponseHeaders = Record<string, string | string[]>;

type Grant = {
  ownerId: number;
  requestId: string;
  active: boolean;
  controller: AbortController;
  authorization?: Promise<SandboxDesktopGrantAuthorization>;
  policy?: SandboxDesktopGrantPolicy;
  credential: string;
  frameTreeNodeId: number | null;
  expiresAt: number | null;
  timer?: ReturnType<typeof setTimeout>;
  cleanup?: Promise<void>;
};
const MAX_REQUESTS_PER_OWNER = 1024;
const MAX_ACTIVE_PER_OWNER = 8;

/** Credentials never leave this main-process registry except in exact authorized request headers. */
export class SandboxDesktopGrantRegistry {
  readonly #deps: SandboxDesktopGrantRegistryDependencies;
  readonly #owners = new Map<number, Map<string, Grant>>();
  readonly #requests = new Map<number, Grant>();
  #transitions = 0;
  #transitionTail: Promise<void> = Promise.resolve();
  constructor(dependencies: SandboxDesktopGrantRegistryDependencies) {
    this.#deps = dependencies;
  }

  async open(
    ownerId: number,
    mainFrameTreeNodeId: number,
    input: unknown,
  ): Promise<SandboxDesktopGrantReply> {
    if (this.#transitions > 0) throw failure('authority_transition');
    const request = parseSandboxDesktopGrantOpen(input);
    if (
      !Number.isSafeInteger(ownerId) ||
      ownerId <= 0 ||
      !Number.isSafeInteger(mainFrameTreeNodeId) ||
      mainFrameTreeNodeId <= 0
    )
      throw failure('owner_invalid');
    const owner = this.#owner(ownerId);
    if (owner.has(request.requestId)) throw failure('request_reused');
    if (
      owner.size >= MAX_REQUESTS_PER_OWNER ||
      [...owner.values()].filter((item) => item.active).length >= MAX_ACTIVE_PER_OWNER
    )
      throw failure('capacity_exceeded');
    const grant: Grant = {
      ownerId,
      requestId: request.requestId,
      active: true,
      controller: new AbortController(),
      credential: '',
      frameTreeNodeId: null,
      expiresAt: null,
    };
    owner.set(request.requestId, grant);
    grant.timer = setTimeout(() => {
      void this.#retire(grant).catch(() => undefined);
    }, this.#deps.openTimeoutMs ?? 15000);
    try {
      grant.authorization = Promise.resolve().then(() =>
        this.#deps.authorize(request, grant.controller.signal),
      );
      const pendingAuthorization = grant.authorization;
      const forgetAuthorization = () => {
        grant.authorization = undefined;
      };
      void pendingAuthorization.then(forgetAuthorization, forgetAuthorization);
      const authorization = await abortable(pendingAuthorization, grant.controller.signal);
      if (!grant.active) throw failure('revoked');
      if (
        typeof authorization.credential !== 'string' ||
        !authorization.credential ||
        authorization.credential !== authorization.credential.trim() ||
        /[\u0000-\u001f\u007f]/u.test(authorization.credential)
      )
        throw failure('authorization_invalid');
      const expiration =
        authorization.expiresAt == null ? null : Date.parse(authorization.expiresAt);
      if (expiration !== null && (!Number.isFinite(expiration) || expiration <= this.#now()))
        throw failure('expired');
      grant.policy = createSandboxDesktopGrantPolicy(request, {
        ownerId,
        mainFrameTreeNodeId,
        apiBaseUrl: authorization.apiBaseUrl,
        grantId: this.#deps.randomId(),
      });
      grant.credential = authorization.credential;
      grant.expiresAt = expiration;
      if (grant.timer) clearTimeout(grant.timer);
      grant.timer = undefined;
      this.#scheduleExpiry(grant);
      return sandboxDesktopGrantReply(grant.policy);
    } catch (error) {
      const reason = grant.controller.signal.aborted
        ? 'revoked'
        : error instanceof Error && error.message === 'sandbox_desktop_grant_expired'
          ? 'expired'
          : 'open_failed';
      void this.#retire(grant).catch(() => undefined);
      // Neither an authorization failure nor its URL/credential details cross IPC.
      throw failure(reason);
    }
  }

  withAuthorityTransition<T>(operation: () => Promise<T>): Promise<T> {
    // Admission closes synchronously, before revocation or any preceding transition awaits.
    this.#transitions += 1;
    const previous = this.#transitionTail;
    const revoked = this.revokeAll();
    const result = (async () => {
      try {
        await Promise.all([previous, revoked]);
        return await operation();
      } finally {
        this.#transitions -= 1;
      }
    })();
    this.#transitionTail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  close(ownerId: number, input: unknown): Promise<void> {
    const request = parseSandboxDesktopGrantClose(input);
    const owner = this.#owner(ownerId);
    const grant = owner.get(request.requestId);
    if (!grant) {
      if (owner.size >= MAX_REQUESTS_PER_OWNER) throw failure('capacity_exceeded');
      // A close received before its open IPC is a tombstone; the later open cannot revive it.
      owner.set(request.requestId, {
        ownerId,
        requestId: request.requestId,
        active: false,
        controller: new AbortController(),
        credential: '',
        frameTreeNodeId: null,
        expiresAt: null,
      });
      return Promise.resolve();
    }
    if (request.grantId !== undefined && request.grantId !== grant.policy?.grantId)
      throw failure('grant_mismatch');
    return this.#retire(grant);
  }
  revokeOwner(ownerId: number): Promise<void> {
    return finishAll(
      [...(this.#owners.get(ownerId)?.values() ?? [])].map((grant) => this.#retire(grant)),
    );
  }
  revokeAll(): Promise<void> {
    const pending: Promise<void>[] = [];
    for (const owner of this.#owners.values())
      for (const grant of owner.values()) pending.push(this.#retire(grant));
    return finishAll(pending);
  }

  /** Called for every navigation, including non-HTTP destinations such as about:blank. */
  observeFrameNavigation(ownerId: number, frameTreeNodeId: number, url: string): void {
    for (const grant of this.#owners.get(ownerId)?.values() ?? []) {
      if (
        grant.active &&
        grant.frameTreeNodeId === frameTreeNodeId &&
        url !== grant.policy?.frameUrl
      )
        void this.#retire(grant).catch(() => undefined);
    }
  }
  observeFrameDestroyed(ownerId: number, frameTreeNodeId: number): void {
    for (const grant of this.#owners.get(ownerId)?.values() ?? []) {
      if (grant.frameTreeNodeId !== frameTreeNodeId) continue;
      grant.frameTreeNodeId = null;
      void this.#retire(grant).catch(() => undefined);
    }
  }

  beforeRequest(
    details: SandboxDesktopGrantNetworkDetails,
    headers: Record<string, string>,
  ): SandboxDesktopGrantHeaderDecision {
    const previous = this.#requests.get(details.id);
    if (details.resourceType === 'subFrame' && details.frame)
      this.observeFrameNavigation(
        details.webContentsId ?? -1,
        details.frame.frameTreeNodeId,
        details.url,
      );
    const owners = this.#owners.get(details.webContentsId ?? -1);
    for (const grant of owners?.values() ?? []) {
      if (!grant.active || !grant.policy) continue;
      if (grant.expiresAt !== null && grant.expiresAt <= this.#now()) {
        void this.#retire(grant).catch(() => undefined);
        continue;
      }
      try {
        const admitted = authorizeSandboxDesktopGrantRequest(
          grant.policy,
          grant.frameTreeNodeId,
          details,
        );
        grant.frameTreeNodeId = admitted.frameTreeNodeId;
        this.#requests.set(details.id, grant);
        const requestHeaders: Record<string, string> = {};
        for (const [key, value] of Object.entries(headers))
          if (!['authorization', 'cookie', 'proxy-authorization'].includes(key.toLowerCase()))
            requestHeaders[key] = value;
        requestHeaders.Authorization = `Bearer ${grant.credential}`;
        return { kind: 'authorized', requestHeaders };
      } catch {
        /* Try another independent frame grant, never another credential transport. */
      }
    }
    if (previous || this.#isTarget(details.url)) return { kind: 'blocked' };
    return { kind: 'unrelated' };
  }
  responseHeaders(
    details: Pick<SandboxDesktopGrantNetworkDetails, 'id' | 'url'>,
    headers: SandboxDesktopResponseHeaders,
  ): SandboxDesktopResponseHeaders {
    if (!this.#requests.has(details.id) && !this.#isTarget(details.url)) return headers;
    return Object.fromEntries(
      Object.entries(headers).filter(([key]) => key.toLowerCase() !== 'set-cookie'),
    );
  }
  completeRequest(id: number): void {
    this.#requests.delete(id);
  }

  #owner(ownerId: number): Map<string, Grant> {
    if (!Number.isSafeInteger(ownerId) || ownerId <= 0) throw failure('owner_invalid');
    let owner = this.#owners.get(ownerId);
    if (!owner) {
      owner = new Map();
      this.#owners.set(ownerId, owner);
    }
    return owner;
  }
  #now(): number {
    return this.#deps.now?.() ?? Date.now();
  }
  #scheduleExpiry(grant: Grant): void {
    if (grant.expiresAt === null || !grant.active) return;
    grant.timer = setTimeout(
      () => {
        if (grant.expiresAt !== null && grant.expiresAt <= this.#now())
          void this.#retire(grant).catch(() => undefined);
        else this.#scheduleExpiry(grant);
      },
      Math.max(1, Math.min(2147483647, grant.expiresAt - this.#now())),
    );
  }
  #isTarget(value: string): boolean {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      return false;
    }
    for (const owner of this.#owners.values())
      for (const grant of owner.values()) {
        const policy = grant.policy;
        if (
          policy &&
          [policy.origin, policy.websocketOrigin].includes(url.origin) &&
          url.pathname.startsWith(policy.proxyPrefix)
        )
          return true;
      }
    return false;
  }
  #retire(grant: Grant): Promise<void> {
    // Revoke synchronously. The asynchronous cleanup below cannot admit a late request.
    grant.active = false;
    grant.credential = '';
    grant.controller.abort();
    if (grant.timer) clearTimeout(grant.timer);
    grant.timer = undefined;
    if (!grant.cleanup)
      grant.cleanup = (async () => {
        await grant.authorization?.catch(() => undefined);
        if (grant.frameTreeNodeId !== null)
          await this.#deps.blankFrame(grant.ownerId, grant.frameTreeNodeId);
      })();
    return grant.cleanup;
  }
}
function failure(reason: string): Error {
  return new Error('sandbox_desktop_grant_' + reason);
}
async function finishAll(pending: Promise<void>[]): Promise<void> {
  const results = await Promise.allSettled(pending);
  const failed = results.find((result) => result.status === 'rejected');
  if (failed?.status === 'rejected') throw failed.reason;
}
function abortable<T>(pending: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const abort = () => reject(failure('revoked'));
    if (signal.aborted) {
      reject(failure('revoked'));
      return;
    }
    signal.addEventListener('abort', abort, { once: true });
    pending.then(
      (value) => {
        signal.removeEventListener('abort', abort);
        resolve(value);
      },
      (error) => {
        signal.removeEventListener('abort', abort);
        reject(error);
      },
    );
  });
}
