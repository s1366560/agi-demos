import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
} from '@/plugins/webOperationAdmissionV2';
/**
 * PlaybookLibrary — read-only view of the project's reflection loop.
 *
 * Two stacked sections:
 *  1. Distilled playbooks (active patterns the reflector has learned).
 *  2. Reflection verdicts timeline (audit log of CREATE / REINFORCE
 *     / DEPRECATE / NOOP decisions).
 *
 * Both views are paginated by limit only — the reflection loop is
 * naturally bounded per project so client-side filtering is sufficient
 * for the foreseeable future.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { FC } from 'react';

import { useParams } from 'react-router-dom';

import { PlaybookLibraryView } from './PlaybookLibraryView';

import { unifiedEventService } from '@/services/unifiedEventService';

import {
  type Playbook,
  type ReflectionVerdict,
  playbookService,
} from '../services/playbookService';

const LIMIT = 200;
const POLL_INTERVAL_MS = 30_000;
const EVENT_REFRESH_DEBOUNCE_MS = 1200;

export const PlaybookLibrary: FC = () => {
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const { projectId } = useParams<{ projectId: string }>();
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [verdicts, setVerdicts] = useState<ReflectionVerdict[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sequenceOwnerRef = useRef<object | null>(null);
  const lastSequenceRef = useRef<string | undefined>(undefined);
  const activeProjectIdRef = useRef<string | undefined>(projectId);
  const sequenceProjectIdRef = useRef<string | undefined>(projectId);
  const refreshTimerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    activeProjectIdRef.current = projectId;
    if (sequenceProjectIdRef.current !== projectId) {
      sequenceProjectIdRef.current = projectId;
      lastSequenceRef.current = undefined;
    }
    return () => {
      if (activeProjectIdRef.current === projectId) {
        activeProjectIdRef.current = undefined;
      }
    };
  }, [projectId]);

  const load = useCallback(
    async (silent?: boolean) => {
      if (projectId === undefined) return;
      const requestedProjectId = projectId;
      if (silent !== true) setLoading(true);
      setError(null);
      try {
        const [pbs, vds] = await Promise.all([
          playbookService.listPlaybooks(requestedProjectId, LIMIT),
          playbookService.listReflectionVerdicts(requestedProjectId, LIMIT),
        ]);
        if (activeProjectIdRef.current !== requestedProjectId) return;
        setPlaybooks(pbs);
        setVerdicts(vds);
      } catch (err) {
        if (activeProjectIdRef.current !== requestedProjectId) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (activeProjectIdRef.current === requestedProjectId && silent !== true) {
          setLoading(false);
        }
      }
    },
    [projectId]
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Background refresh: the reflection loop runs out-of-band, so poll
  // periodically while the page is visible to keep the view fresh
  // without requiring a dedicated project-event channel.
  useEffect(() => {
    if (projectId === undefined) return;
    const handle = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void load(true);
      }
    }, POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [projectId, load]);

  useEffect(() => {
    if (projectId === undefined || !availability.available) return;
    if (sequenceOwnerRef.current !== availability.owner) {
      sequenceOwnerRef.current = availability.owner;
      lastSequenceRef.current = undefined;
    }

    const unsubscribe = unifiedEventService.subscribeProject(
      projectId,
      (event) => {
        if (getWebOperationAvailabilityV2() !== availability) return;
        if (event.type !== 'reflection_complete') {
          return;
        }
        if (event.sequence_id) {
          lastSequenceRef.current = event.sequence_id;
        }
        if (refreshTimerRef.current) {
          window.clearTimeout(refreshTimerRef.current);
        }
        refreshTimerRef.current = window.setTimeout(() => {
          if (getWebOperationAvailabilityV2() !== availability) return;
          void load(true);
          refreshTimerRef.current = undefined;
        }, EVENT_REFRESH_DEBOUNCE_MS);
      },
      lastSequenceRef.current
    );

    return () => {
      unsubscribe();
      if (refreshTimerRef.current) {
        window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = undefined;
      }
    };
  }, [projectId, load, availability]);

  return (
    <PlaybookLibraryView
      playbooks={playbooks}
      verdicts={verdicts}
      loading={loading}
      error={error}
      onRefresh={() => void load()}
    />
  );
};

export default PlaybookLibrary;
