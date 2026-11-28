type TenantCleanup = () => void | Promise<void>;

const listeners = new Set<TenantCleanup>();

/** Loaded runtimes own their scope-bound state and connections. */
export function onTenantScopeRetired(cleanup: TenantCleanup) {
  listeners.add(cleanup);
  return () => {
    listeners.delete(cleanup);
  };
}

export async function retireTenantScope(): Promise<void> {
  const results = await Promise.allSettled([...listeners].map(async (cleanup) => cleanup()));
  const failure = results.find((result) => result.status === 'rejected');
  if (failure?.status === 'rejected') throw failure.reason;
}
