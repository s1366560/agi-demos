/**
 * Virtualized Message List.
 *
 * Provides efficient rendering of long conversation histories using virtual scrolling.
 * Only renders visible messages plus a small buffer for smooth scrolling.
 *
 * Features:
 * - Automatic virtualization with @tanstack/react-virtual
 * - Sticky scroll-to-bottom when new messages arrive
 * - Smooth scrolling with scroll restoration
 * - Support for variable message heights
 *
 * @example
 * <VirtualizedMessageList
 *   messages={messages}
 *   onMessageClick={handleMessageClick}
 *   className="h-full"
 * />
 */

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

import { ChatMessage } from '../types/message';

import { MessageRenderer } from './MessageRenderer';

export interface VirtualizedMessageListProps {
  /** Messages to render */
  messages: ChatMessage[];
  /** Container height (required for virtualization) */
  height?: number | string;
  /** Estimated message height for initial render */
  estimatedHeight?: number;
  /** Number of messages to render outside visible area */
  overscan?: number;
  /** Custom CSS classes */
  className?: string;
  /** Whether to auto-scroll to bottom on new messages */
  autoScroll?: boolean;
  /** Scroll offset threshold for auto-scroll */
  scrollThreshold?: number;
  /** Message click handler */
  onMessageClick?: (message: ChatMessage) => void;
  /** Message retry handler */
  onRetry?: (messageId: string) => void;
  /** Message copy handler */
  onCopy?: (messageId: string) => void;
  /** Message delete handler */
  onDelete?: (messageId: string) => void;
  /** Loading state */
  isLoading?: boolean;
  /** Empty state content */
  emptyState?: React.ReactNode;
  /** Loading state content */
  loadingState?: React.ReactNode;
}

/**
 * Default estimated message height (pixels).
 * Used for initial virtual scroll calculation.
 */
const DEFAULT_ESTIMATED_HEIGHT = 120;

/**
 * Default overscan count.
 * Number of messages to render outside visible area for smooth scrolling.
 */
const DEFAULT_OVERSCAN = 3;

/**
 * Scroll threshold for auto-scroll (pixels from bottom).
 */
const DEFAULT_SCROLL_THRESHOLD = 100;

export const VirtualizedMessageList: React.FC<VirtualizedMessageListProps> = ({
  messages,
  height = '100%',
  estimatedHeight = DEFAULT_ESTIMATED_HEIGHT,
  overscan = DEFAULT_OVERSCAN,
  className = '',
  autoScroll = true,
  scrollThreshold = DEFAULT_SCROLL_THRESHOLD,
  onMessageClick,
  onRetry,
  onCopy,
  onDelete,
  isLoading = false,
  emptyState,
  loadingState,
}) => {
  // Parent ref for virtualizer
  const parentRef = useRef<HTMLDivElement>(null);
  
  // Track if user is near bottom
  const [isNearBottom, setIsNearBottom] = useState(true);
  
  // Track last message count for auto-scroll decision
  const lastMessageCount = useRef(messages.length);
  
  // Virtualizer instance
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => estimatedHeight,
    overscan,
    // Enable smooth scrolling
    scrollPaddingStart: 20,
    scrollPaddingEnd: 20,
  });

  /**
   * Handle scroll events to track if near bottom.
   */
  const handleScroll = useCallback(() => {
    if (!parentRef.current) return;
    
    const { scrollTop, scrollHeight, clientHeight } = parentRef.current;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    setIsNearBottom(distanceFromBottom <= scrollThreshold);
  }, [scrollThreshold]);

  /**
   * Auto-scroll to bottom when new messages arrive.
   * Only scrolls if user was already near bottom.
   */
  useEffect(() => {
    if (!autoScroll || !parentRef.current) return;
    
    // Only auto-scroll if:
    // 1. New messages were added
    // 2. User was near bottom
    const hasNewMessages = messages.length > lastMessageCount.current;
    
    if (hasNewMessages && isNearBottom) {
      // Smooth scroll to bottom
      parentRef.current.scrollTo({
        top: parentRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
    
    lastMessageCount.current = messages.length;
  }, [messages.length, autoScroll, isNearBottom]);

  /**
   * Auto-scroll when content size changes (e.g. streaming responses).
   * Keeps the view at the bottom if the user was already at the bottom.
   */
  useEffect(() => {
    if (!autoScroll || !parentRef.current) return;
    
    // Check if we were near bottom BEFORE this size change
    // Note: isNearBottom state might be slightly stale if a scroll event hasn't fired yet
    // but usually it's close enough.
    
    if (isNearBottom) {
       // Use 'auto' behavior for streaming updates to prevent smooth scroll lag
       parentRef.current.scrollTo({
         top: parentRef.current.scrollHeight,
         behavior: 'auto',
       });
    }
  }, [virtualizer.getTotalSize(), autoScroll, isNearBottom]);

  /**
   * Set up scroll listener.
   */
  useEffect(() => {
    const element = parentRef.current;
    if (!element) return;
    
    element.addEventListener('scroll', handleScroll, { passive: true });
    return () => element.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  /**
   * Render empty state.
   */
  if (messages.length === 0 && !isLoading) {
    return (
      <div className={`flex items-center justify-center h-full ${className}`}>
        {emptyState || (
          <div className="text-center text-slate-500 dark:text-slate-400">
            <p className="text-lg font-medium">No messages yet</p>
            <p className="text-sm mt-1">Start a conversation!</p>
          </div>
        )}
      </div>
    );
  }

  /**
   * Render loading state.
   */
  if (isLoading) {
    return (
      <div className={`flex items-center justify-center h-full ${className}`}>
        {loadingState || (
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            <p className="text-slate-500 dark:text-slate-400">Loading messages...</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      ref={parentRef}
      className={`overflow-auto ${className}`}
      style={{ height: typeof height === 'string' ? height : `${height}px` }}
      role="log"
      aria-label="Chat messages"
      aria-live="polite"
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const message = messages[virtualRow.index];
          const isLatest = virtualRow.index === messages.length - 1;
          
          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <MessageRenderer
                message={message}
                isLatest={isLatest}
                onRetry={onRetry}
                onCopy={onCopy}
                onDelete={onDelete}
                onClick={onMessageClick}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default VirtualizedMessageList;
