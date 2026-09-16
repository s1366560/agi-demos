import { useCallback, useRef, useState } from 'react';

import type { AgentConversation, ChangeSnapshot, DesktopRun, DesktopRuntimeConfig } from '../../types';
import {
  buildChangeRevertPayload,
  changeRevertAvailable,
  changeRevertNoticeFromError,
  revertRunChanges,
  type ChangeRevertNotice,
  type ChangeRevertSelector,
} from './sessionChangesRevertModel';

type Options = {
  config: DesktopRuntimeConfig;
  conversation: AgentConversation | null;
  run: DesktopRun | null;
  snapshot: ChangeSnapshot | null;
  onReverted: () => void;
};

export type ChangeRevertSurface = {
  available: boolean;
  pending: boolean;
  notice: ChangeRevertNotice | null;
  requestRevert: (selector: ChangeRevertSelector) => void;
  dismissNotice: () => void;
};

/**
 * Drives the Changes panel revert flow: the canvas collects explicit user
 * confirmation (the HITL gate), then this hook sends the digest-pinned
 * selectors and, on success, refreshes the snapshot so reverted entries
 * disappear and stale comment anchors invalidate naturally.
 */
export function useRunChangeRevert({
  config,
  conversation,
  run,
  snapshot,
  onReverted,
}: Options): ChangeRevertSurface {
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<ChangeRevertNotice | null>(null);
  const inFlightRef = useRef(false);
  const dismissNotice = useCallback(() => setNotice(null), []);
  const requestRevert = useCallback(
    (selector: ChangeRevertSelector) => {
      if (inFlightRef.current) return;
      if (!snapshot || !run || !conversation || run.id !== snapshot.run_id) return;
      if (snapshot.conversation_id !== conversation.id) return;
      const key = globalThis.crypto?.randomUUID?.() ?? `revert-${Date.now()}`;
      const payload = buildChangeRevertPayload(snapshot, selector, key);
      if (!payload) {
        setNotice({ kind: 'failed', reasonCode: 'revert_payload_invalid' });
        return;
      }
      inFlightRef.current = true;
      setPending(true);
      setNotice(null);
      const controller = new AbortController();
      void revertRunChanges(config, run.id, payload, controller.signal)
        .then(() => {
          setNotice(null);
          onReverted();
        })
        .catch((error: unknown) => {
          setNotice(changeRevertNoticeFromError(error));
        })
        .finally(() => {
          inFlightRef.current = false;
          setPending(false);
        });
    },
    [config, conversation, onReverted, run, snapshot],
  );
  return {
    available: changeRevertAvailable(config, snapshot),
    pending,
    notice,
    requestRevert,
    dismissNotice,
  };
}
