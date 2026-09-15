/** Batch socket events without depending on a visible renderer's animation clock. */
export function scheduleAgentSocketEventFlush(flush: () => void): () => void {
  let pending = true;
  let frame: number | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const cancel = () => {
    pending = false;
    if (frame !== null) cancelAnimationFrame(frame);
    if (timer !== null) clearTimeout(timer);
  };
  const run = () => {
    if (!pending) return;
    cancel();
    flush();
  };
  if (typeof requestAnimationFrame === 'function') {
    frame = requestAnimationFrame(run);
  }
  timer = setTimeout(run, 16);
  return cancel;
}

/** Build the newest-first socket window consumed by chronological event readers. */
export function prependAgentSocketEvents<T>(
  current: readonly T[],
  pending: readonly T[],
  limit: number,
): T[] {
  return [...[...pending].reverse(), ...current].slice(0, limit);
}
