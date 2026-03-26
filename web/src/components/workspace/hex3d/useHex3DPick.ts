import { useState, useCallback } from 'react';

export interface HexCoordinates {
  q: number;
  r: number;
}

interface UseHex3DPickOptions {
  onSelectHex?: (q: number, r: number) => void;
  onContextMenu?: (q: number, r: number, e: MouseEvent) => void;
}

export function useHex3DPick(options?: UseHex3DPickOptions) {
  const [selectedHex, setSelectedHex] = useState<HexCoordinates | null>(null);
  const [hoveredHex, setHoveredHex] = useState<HexCoordinates | null>(null);

  const handleHexClick = useCallback(
    (q: number, r: number) => {
      setSelectedHex({ q, r });
      options?.onSelectHex?.(q, r);
    },
    [options]
  );

  const handleHexHover = useCallback((q: number | null, r: number | null) => {
    if (q === null || r === null) {
      setHoveredHex(null);
    } else {
      setHoveredHex({ q, r });
    }
  }, []);

  const handleHexContextMenu = useCallback(
    (q: number, r: number, e: MouseEvent) => {
      setSelectedHex({ q, r });
      options?.onContextMenu?.(q, r, e);
    },
    [options]
  );

  return {
    selectedHex,
    hoveredHex,
    handleHexClick,
    handleHexHover,
    handleHexContextMenu,
  };
}
