import { useState, useCallback } from 'react';

import type { WorkspaceAgent } from '@/types/workspace';

export interface HexCoordinates {
  q: number;
  r: number;
}

export interface HexCandidate {
  q: number;
  r: number;
  distance: number;
}

interface UseHex3DPickOptions {
  onSelectHex?: (q: number, r: number) => void;
  onContextMenu?: (q: number, r: number, e: MouseEvent) => void;
  agents?: WorkspaceAgent[];
}

export function pickBestHexId(
  candidates: HexCandidate[],
  agents: WorkspaceAgent[]
): HexCoordinates | null {
  if (candidates.length === 0) return null;

  const agentHexes = new Set(
    agents
      .filter((a) => a.hex_q !== undefined && a.hex_r !== undefined)
      .map((a) => String(a.hex_q) + ',' + String(a.hex_r))
  );

  let bestCandidate = candidates[0];
  let bestHasAgent = agentHexes.has(String(bestCandidate.q) + ',' + String(bestCandidate.r));

  for (let i = 1; i < candidates.length; i++) {
    const candidate = candidates[i];
    const hasAgent = agentHexes.has(String(candidate.q) + ',' + String(candidate.r));

    if (hasAgent && !bestHasAgent) {
      bestCandidate = candidate;
      bestHasAgent = true;
    } else if (hasAgent === bestHasAgent) {
      if (candidate.distance < bestCandidate.distance) {
        bestCandidate = candidate;
      }
    }
  }

  return { q: bestCandidate.q, r: bestCandidate.r };
}

export function useHex3DPick(options?: UseHex3DPickOptions) {
  const [selectedHex, setSelectedHex] = useState<HexCoordinates | null>(null);
  const [hoveredHex, setHoveredHex] = useState<HexCoordinates | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

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

  const handleAgentSelect = useCallback(
    (agentId: string) => {
      setSelectedAgentId(agentId);
      if (options?.agents) {
        const agent = options.agents.find((a) => a.agent_id === agentId);
        if (agent && agent.hex_q !== undefined && agent.hex_r !== undefined) {
          setSelectedHex({ q: agent.hex_q, r: agent.hex_r });
        }
      }
    },
    [options]
  );

  return {
    selectedHex,
    hoveredHex,
    selectedAgentId,
    handleHexClick,
    handleHexHover,
    handleHexContextMenu,
    handleAgentSelect,
    setSelectedAgentId,
  };
}
