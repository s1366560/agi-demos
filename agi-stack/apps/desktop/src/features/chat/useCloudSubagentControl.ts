import { useCallback, useEffect, useRef, useState } from 'react';
import type { DesktopRuntimeConfig } from '../../types';
import type { SubAgentControlCommand } from '../../hooks/useAgentSocket';
import type { SubAgentControlAuthority } from './subagentControlAuthorityModel';
import { loadCloudChildAuthority, sendCloudChildControl } from './cloudSubagentControlClient';

const unavailable: SubAgentControlAuthority = { availability: 'unavailable', reasonCode: 'cloud_child_control_snapshot_unavailable',
  allowedActions: [], authorityRevision: null, conversationId: null, participantAgentIds: [] };

/** Scope-bound polling also follows detached children after the parent's stream ends. */
export function useCloudSubagentControl(config: DesktopRuntimeConfig, conversationId: string | null) {
  const [snapshot, setSnapshot] = useState<{ key: string; authority: SubAgentControlAuthority } | null>(null);
  const key = JSON.stringify([config.mode, config.apiBaseUrl, config.tenantId, config.projectId, conversationId]);
  const refreshRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (config.mode !== 'cloud' || !conversationId) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    const load = async () => {
      if (timer !== null) clearTimeout(timer);
      controller?.abort();
      const current = new AbortController();
      controller = current;
      try {
        const authority = await loadCloudChildAuthority(config, conversationId, current.signal);
        if (!disposed && !current.signal.aborted) setSnapshot({ key, authority });
      } catch {
        if (!disposed && !current.signal.aborted) setSnapshot({ key, authority: unavailable });
      } finally {
        if (!disposed && !current.signal.aborted) timer = setTimeout(() => void load(), 3000);
      }
    };
    refreshRef.current = () => void load();
    void load();
    return () => { disposed = true; controller?.abort(); if (timer !== null) clearTimeout(timer); refreshRef.current = null; };
  }, [config, conversationId, key]);
  const sendControl = useCallback(async (command: SubAgentControlCommand) => {
    const receipt = await sendCloudChildControl(config, command);
    refreshRef.current?.();
    return receipt;
  }, [config]);
  return { authority: snapshot?.key === key ? snapshot.authority : unavailable, sendControl };
}
