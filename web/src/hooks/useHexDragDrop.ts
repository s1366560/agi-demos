import { useState, useCallback } from 'react';

interface HexCoord {
  q: number;
  r: number;
}

export function useHexDragDrop() {
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [draggedAgentId, setDraggedAgentId] = useState<string | null>(null);
  const [dragOrigin, setDragOrigin] = useState<HexCoord | null>(null);
  const [dragTarget, setDragTarget] = useState<HexCoord | null>(null);

  const startDrag = useCallback((agentId: string, q: number, r: number) => {
    setIsDragging(true);
    setDraggedAgentId(agentId);
    setDragOrigin({ q, r });
    setDragTarget({ q, r });
  }, []);

  const updateDragTarget = useCallback((q: number, r: number) => {
    setDragTarget(prev => {
      if (prev && prev.q === q && prev.r === r) return prev;
      return { q, r };
    });
  }, []);

  const cancelDrag = useCallback(() => {
    setIsDragging(false);
    setDraggedAgentId(null);
    setDragOrigin(null);
    setDragTarget(null);
  }, []);

  const endDrag = useCallback((
    onMoveAgent?: (agentId: string, q: number, r: number) => void
  ) => {
    if (isDragging && draggedAgentId && dragTarget && onMoveAgent) {
      if (!dragOrigin || dragOrigin.q !== dragTarget.q || dragOrigin.r !== dragTarget.r) {
        onMoveAgent(draggedAgentId, dragTarget.q, dragTarget.r);
      }
    }
    
    cancelDrag();
  }, [isDragging, draggedAgentId, dragTarget, dragOrigin, cancelDrag]);

  return {
    isDragging,
    draggedAgentId,
    dragOrigin,
    dragTarget,
    startDrag,
    updateDragTarget,
    endDrag,
    cancelDrag,
  };
}
