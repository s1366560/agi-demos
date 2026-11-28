import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Playbook, ReflectionVerdict } from '../web/services/playbookService';

export function useReflectionLibrary() {
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [verdicts, setVerdicts] = useState<ReflectionVerdict[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  const load = useCallback(async (silent = false) => {
    if (silent && pending.current) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    if (!silent) setLoading(true);
    try {
      const options = { signal: controller.signal };
      const [books, decisions] = await Promise.all([
        window.memstack.invoke('list-playbooks', undefined, options) as Promise<{ items: Playbook[] }>,
        window.memstack.invoke('list-verdicts', undefined, options) as Promise<{
          items: ReflectionVerdict[];
        }>,
      ]);
      if (controller.signal.aborted) return;
      setPlaybooks(books.items);
      setVerdicts(decisions.items);
      setError(null);
    } catch (cause) {
      if (!controller.signal.aborted)
        setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (pending.current === controller) pending.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load(true);
    }, 30_000);
    return () => {
      window.clearInterval(timer);
      pending.current?.abort();
    };
  }, [load]);
  return { playbooks, verdicts, loading, error, onRefresh: () => void load() };
}
