import { useCallback } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';

import { hexDistance } from '@/components/workspace/hex/useHexLayout';

import {
  coordKey,
  HEX_KEY_OFFSETS,
  isEditableTarget,
  RESERVED_CENTER_KEY,
} from './arrangementUtils';

import type { TopologyNode, WorkspaceAgent } from '@/types/workspace';

import type { SelectionState, ViewMode } from './arrangementUtils';

interface UseArrangementKeyboardParams {
  selection: SelectionState | null;
  viewMode: ViewMode;
  keyboardCursor: { q: number; r: number };
  gridRadius: number;
  agentByCoord: Map<string, WorkspaceAgent>;
  nodeByCoord: Map<string, TopologyNode>;
  setSelection: (s: SelectionState | null) => void;
  setMoveMode: (m: null) => void;
  setViewMode: (v: ViewMode) => void;
  setZoom: (fn: (current: number) => number) => void;
  setKeyboardCursor: (fn: (current: { q: number; r: number }) => { q: number; r: number }) => void;
  setAddAgentOpen: (v: boolean) => void;
  resetView: () => void;
  nudgePan: (x: number, y: number) => void;
  handleActivateHex: (q: number, r: number) => Promise<void>;
  handleCreateNode: (
    nodeType: TopologyNode['node_type'],
    targetHex?: { q: number; r: number }
  ) => Promise<void>;
  handleDeleteSelection: () => Promise<void>;
  beginMoveMode: () => void;
}

export function useArrangementKeyboard(
  params: UseArrangementKeyboardParams
): (event: ReactKeyboardEvent<HTMLDivElement>) => void {
  const handleBoardKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (isEditableTarget(event.target)) {
        return;
      }

      if (event.key === 'Escape') {
        params.setMoveMode(null);
        params.setSelection(null);
        return;
      }

      if (event.key === '2') {
        params.setViewMode('2d');
        return;
      }

      if (event.key === '3') {
        params.setViewMode('3d');
        return;
      }

      if (event.key === '0') {
        event.preventDefault();
        params.resetView();
        return;
      }

      if (event.key === '+' || event.key === '=') {
        event.preventDefault();
        params.setZoom((current) => Math.min(2.2, current + 0.15));
        return;
      }

      if (event.key === '-') {
        event.preventDefault();
        params.setZoom((current) => Math.max(0.55, current - 0.15));
        return;
      }

      if (event.shiftKey && event.key in HEX_KEY_OFFSETS) {
        event.preventDefault();

        if (event.key === 'ArrowUp') {
          params.nudgePan(0, 28);
          return;
        }
        if (event.key === 'ArrowDown') {
          params.nudgePan(0, -28);
          return;
        }
        if (event.key === 'ArrowLeft') {
          params.nudgePan(28, 0);
          return;
        }
        if (event.key === 'ArrowRight') {
          params.nudgePan(-28, 0);
        }
        return;
      }

      if (params.viewMode === '2d' && event.key in HEX_KEY_OFFSETS) {
        event.preventDefault();
        params.setKeyboardCursor((current) => {
          const offset = HEX_KEY_OFFSETS[event.key as keyof typeof HEX_KEY_OFFSETS];
          const next = { q: current.q + offset.q, r: current.r + offset.r };

          if (hexDistance(0, 0, next.q, next.r) > params.gridRadius) {
            return current;
          }

          return next;
        });
        return;
      }

      if (params.viewMode === '2d' && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        void params.handleActivateHex(params.keyboardCursor.q, params.keyboardCursor.r);
        return;
      }

      if (params.selection?.kind === 'empty' && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        params.setAddAgentOpen(true);
        return;
      }

      if (
        params.selection?.kind !== 'empty' &&
        event.key.toLowerCase() === 'a' &&
        !params.agentByCoord.has(coordKey(params.keyboardCursor.q, params.keyboardCursor.r)) &&
        !params.nodeByCoord.has(coordKey(params.keyboardCursor.q, params.keyboardCursor.r)) &&
        coordKey(params.keyboardCursor.q, params.keyboardCursor.r) !== RESERVED_CENTER_KEY
      ) {
        event.preventDefault();
        params.setSelection({
          kind: 'empty',
          q: params.keyboardCursor.q,
          r: params.keyboardCursor.r,
        });
        params.setAddAgentOpen(true);
        return;
      }

      if (params.selection?.kind === 'empty' && event.key.toLowerCase() === 'c') {
        event.preventDefault();
        void params.handleCreateNode('corridor');
        return;
      }

      if (
        params.selection?.kind !== 'empty' &&
        event.key.toLowerCase() === 'c' &&
        !params.agentByCoord.has(coordKey(params.keyboardCursor.q, params.keyboardCursor.r)) &&
        !params.nodeByCoord.has(coordKey(params.keyboardCursor.q, params.keyboardCursor.r)) &&
        coordKey(params.keyboardCursor.q, params.keyboardCursor.r) !== RESERVED_CENTER_KEY
      ) {
        event.preventDefault();
        params.setSelection({
          kind: 'empty',
          q: params.keyboardCursor.q,
          r: params.keyboardCursor.r,
        });
        void params.handleCreateNode('corridor', params.keyboardCursor);
        return;
      }

      if (params.selection?.kind === 'empty' && event.key.toLowerCase() === 'h') {
        event.preventDefault();
        void params.handleCreateNode('human_seat');
        return;
      }

      if (
        params.selection?.kind !== 'empty' &&
        event.key.toLowerCase() === 'h' &&
        !params.agentByCoord.has(coordKey(params.keyboardCursor.q, params.keyboardCursor.r)) &&
        !params.nodeByCoord.has(coordKey(params.keyboardCursor.q, params.keyboardCursor.r)) &&
        coordKey(params.keyboardCursor.q, params.keyboardCursor.r) !== RESERVED_CENTER_KEY
      ) {
        event.preventDefault();
        params.setSelection({
          kind: 'empty',
          q: params.keyboardCursor.q,
          r: params.keyboardCursor.r,
        });
        void params.handleCreateNode('human_seat', params.keyboardCursor);
        return;
      }

      if (
        (params.selection?.kind === 'agent' || params.selection?.kind === 'node') &&
        event.key.toLowerCase() === 'm'
      ) {
        event.preventDefault();
        params.beginMoveMode();
        return;
      }

      if (
        (params.selection?.kind === 'agent' || params.selection?.kind === 'node') &&
        (event.key === 'Delete' || event.key === 'Backspace')
      ) {
        event.preventDefault();
        void params.handleDeleteSelection();
      }
    },
    [params]
  );

  return handleBoardKeyDown;
}
