import { useMemo, useSyncExternalStore } from 'react';
const subscribe = (listener: () => void) => {
  const observer = new MutationObserver(listener);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class', 'data-theme', 'style'],
  });
  return () => observer.disconnect();
};
export function useThemeColors<K extends string>(tokens: Record<K, string>): Record<K, string> {
  const version = useSyncExternalStore(
    subscribe,
    () => document.documentElement.getAttribute('data-theme') + document.documentElement.className
  );
  return useMemo(
    () =>
      Object.fromEntries(
        Object.entries(tokens).map(([key, value]) => [
          key,
          getComputedStyle(document.documentElement).getPropertyValue(String(value)).trim(),
        ])
      ) as Record<K, string>,
    [tokens, version]
  );
}

export function useThemeColor(token: string): string {
  const tokens = useMemo(() => ({ value: token }), [token]);
  return useThemeColors(tokens).value;
}
