import { useCallback, useEffect, useRef, useState } from 'react';

import { message } from 'antd';

import type { GroupedItem } from './groupTimelineEvents';

export interface UseMessageAreaKeyboardParams {
  containerRef: React.RefObject<HTMLDivElement | null>;
  groupedItems: GroupedItem[];
}

export interface UseMessageAreaKeyboardReturn {
  focusedMsgIndex: number;
}

export function useMessageAreaKeyboard(
  params: UseMessageAreaKeyboardParams
): UseMessageAreaKeyboardReturn {
  const { containerRef, groupedItems } = params;

  const focusedMsgRef = useRef<number>(-1);
  const [focusedMsgIndex, setFocusedMsgIndex] = useState(-1);

  const navigableIndices = useCallback(() => {
    const indices: number[] = [];
    groupedItems.forEach((item, idx) => {
      if (item.kind === 'event') {
        const t = item.event.type;
        if (t === 'user_message' || t === 'assistant_message') {
          indices.push(idx);
        }
      }
    });
    return indices;
  }, [groupedItems]);

  useEffect(() => {
    focusedMsgRef.current = focusedMsgIndex;
  }, [focusedMsgIndex]);

  useEffect(() => {
    const handleNav = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput =
        target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;
      if (isInput) return;

      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault();
        const indices = navigableIndices();
        if (indices.length === 0) return;

        const current = focusedMsgRef.current;
        let currentPos = indices.indexOf(current);

        if (e.key === 'j') {
          currentPos = currentPos < indices.length - 1 ? currentPos + 1 : currentPos;
        } else {
          currentPos = currentPos > 0 ? currentPos - 1 : 0;
        }

        const nextIndex = indices[currentPos] ?? 0;
        setFocusedMsgIndex(nextIndex);

        const el = containerRef.current?.querySelector(`[data-msg-index="${String(nextIndex)}"]`);
        if (el) {
          el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
      }

      // c to copy focused message content
      if (e.key === 'c' && focusedMsgRef.current >= 0) {
        const item = groupedItems[focusedMsgRef.current];
        if (item?.kind === 'event') {
          const ev = item.event;
          if (ev.type === 'user_message' || ev.type === 'assistant_message') {
            navigator.clipboard.writeText(ev.content).catch(() => {
              void message.warning('Failed to copy to clipboard');
            });
          }
        }
      }

      // Escape to clear focus
      if (e.key === 'Escape' && focusedMsgRef.current >= 0) {
        setFocusedMsgIndex(-1);
      }
    };

    window.addEventListener('keydown', handleNav);
    return () => {
      window.removeEventListener('keydown', handleNav);
    };
  }, [navigableIndices, groupedItems, containerRef]);

  return { focusedMsgIndex };
}
