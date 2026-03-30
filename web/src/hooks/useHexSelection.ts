import { useState, useCallback } from 'react';

export function useHexSelection() {
  const [selectedHexes, setSelectedHexes] = useState<Set<string>>(new Set());

  const isSelected = useCallback(
    (q: number, r: number) => {
      return selectedHexes.has(`${q},${r}`);
    },
    [selectedHexes]
  );

  const toggleSelect = useCallback((q: number, r: number) => {
    setSelectedHexes((prev) => {
      const next = new Set(prev);
      const key = `${q},${r}`;
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const selectSingle = useCallback((q: number, r: number) => {
    setSelectedHexes(new Set([`${q},${r}`]));
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedHexes(new Set());
  }, []);

  const selectAll = useCallback((keys: string[]) => {
    setSelectedHexes(new Set(keys));
  }, []);

  return {
    selectedHexes,
    isSelected,
    toggleSelect,
    selectSingle,
    clearSelection,
    selectAll,
  };
}
