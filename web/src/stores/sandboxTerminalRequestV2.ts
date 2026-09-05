import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
} from '../plugins/webOperationAdmissionV2';

interface TerminalScope {
  activeProjectId: string | null;
  activeSandboxId: string | null;
}
interface TerminalStore {
  getState(): TerminalScope;
  setState(state: { isTerminalLoading: boolean }): void;
  subscribe(listener: (state: TerminalScope, previous: TerminalScope) => void): () => void;
}
let latestIntent: object | undefined;
export const terminalRequestRetired = () =>
  new DOMException('Terminal control request retired', 'AbortError');

/** A response may update only the exact project, sandbox, owner and request that issued it. */
export function beginSandboxTerminalRequestV2(store: TerminalStore) {
  const availability = getWebOperationAvailabilityV2();
  if (!availability.available) throw new Error('web_operation_generation_unavailable');
  const scope = store.getState();
  const intent = {};
  latestIntent = intent;
  const retire = () => {
    if (latestIntent !== intent) return;
    latestIntent = undefined;
    store.setState({ isTerminalLoading: false });
  };
  const unsubscribeScope = store.subscribe((state, previous) => {
    if (
      state.activeProjectId !== previous.activeProjectId ||
      state.activeSandboxId !== previous.activeSandboxId
    )
      retire();
  });
  const unsubscribeOwner = subscribeWebOperationAvailabilityV2(() => {
    if (getWebOperationAvailabilityV2().owner !== availability.owner) retire();
  });
  return {
    current: () => {
      const state = store.getState();
      return (
        latestIntent === intent &&
        getWebOperationAvailabilityV2().owner === availability.owner &&
        state.activeProjectId === scope.activeProjectId &&
        state.activeSandboxId === scope.activeSandboxId
      );
    },
    finish: () => {
      unsubscribeScope();
      unsubscribeOwner();
    },
  };
}
