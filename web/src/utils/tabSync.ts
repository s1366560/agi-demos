/**
 * Cross-Tab Synchronization Utility
 * 
 * Uses BroadcastChannel API to synchronize state across browser tabs.
 * This enables real-time sync when the same user has multiple tabs open.
 * 
 * @packageDocumentation
 */

import { logger } from './logger';

/**
 * Message types for cross-tab synchronization
 */
export type TabSyncMessageType =
    | 'USER_MESSAGE_SENT'        // User sent a new message
    | 'STREAMING_STATE_CHANGED'  // Conversation streaming state changed
    | 'CONVERSATION_COMPLETED'   // Conversation streaming completed
    | 'HITL_STATE_CHANGED'       // HITL (Human-in-the-loop) state changed
    | 'CONVERSATION_DELETED'     // Conversation was deleted
    | 'CONVERSATION_RENAMED'     // Conversation was renamed
    | 'REQUEST_SYNC'             // Request current state from other tabs
    | 'SYNC_RESPONSE';           // Response to sync request

/**
 * Base interface for sync messages
 */
interface TabSyncMessageBase {
    type: TabSyncMessageType;
    senderId: string;           // Unique ID of the sending tab
    timestamp: number;
    conversationId?: string;
}

/**
 * User message sent event
 */
export interface UserMessageSentMessage extends TabSyncMessageBase {
    type: 'USER_MESSAGE_SENT';
    conversationId: string;
    messageId: string;
    content: string;
}

/**
 * Streaming state changed event
 */
export interface StreamingStateChangedMessage extends TabSyncMessageBase {
    type: 'STREAMING_STATE_CHANGED';
    conversationId: string;
    isStreaming: boolean;
    streamStatus: 'idle' | 'connecting' | 'streaming' | 'error';
}

/**
 * Conversation completed event
 */
export interface ConversationCompletedMessage extends TabSyncMessageBase {
    type: 'CONVERSATION_COMPLETED';
    conversationId: string;
}

/**
 * HITL state changed event
 */
export interface HITLStateChangedMessage extends TabSyncMessageBase {
    type: 'HITL_STATE_CHANGED';
    conversationId: string;
    hasPendingHITL: boolean;
    hitlType?: 'clarification' | 'decision' | 'env_var';
}

/**
 * Conversation deleted event
 */
export interface ConversationDeletedMessage extends TabSyncMessageBase {
    type: 'CONVERSATION_DELETED';
    conversationId: string;
}

/**
 * Conversation renamed event
 */
export interface ConversationRenamedMessage extends TabSyncMessageBase {
    type: 'CONVERSATION_RENAMED';
    conversationId: string;
    newTitle: string;
}

/**
 * Union type of all sync messages
 */
export type TabSyncMessage =
    | UserMessageSentMessage
    | StreamingStateChangedMessage
    | ConversationCompletedMessage
    | HITLStateChangedMessage
    | ConversationDeletedMessage
    | ConversationRenamedMessage
    | TabSyncMessageBase;

/**
 * Handler type for sync messages
 */
export type TabSyncHandler = (message: TabSyncMessage) => void;

/**
 * Cross-Tab Synchronization Manager
 * 
 * Singleton class that manages BroadcastChannel communication
 * between browser tabs for the same user.
 */
class TabSyncManager {
    private static instance: TabSyncManager | null = null;
    private channel: BroadcastChannel | null = null;
    private handlers: Set<TabSyncHandler> = new Set();
    private tabId: string;
    private isSupported: boolean;

    private constructor() {
        // Generate unique tab ID
        this.tabId = this.generateTabId();

        // Check if BroadcastChannel is supported
        this.isSupported = typeof BroadcastChannel !== 'undefined';

        if (this.isSupported) {
            this.initChannel();
        } else {
            logger.warn('[TabSync] BroadcastChannel not supported in this browser');
        }
    }

    /**
     * Get singleton instance
     */
    static getInstance(): TabSyncManager {
        if (!TabSyncManager.instance) {
            TabSyncManager.instance = new TabSyncManager();
        }
        return TabSyncManager.instance;
    }

    /**
     * Generate a unique ID for this tab
     */
    private generateTabId(): string {
        if (typeof crypto !== 'undefined' && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        return `${Date.now()}-${Math.random().toString(36).substring(2, 15)}`;
    }

    /**
     * Initialize the BroadcastChannel
     */
    private initChannel(): void {
        try {
            this.channel = new BroadcastChannel('memstack-agent-sync');

            this.channel.onmessage = (event: MessageEvent<TabSyncMessage>) => {
                // Ignore messages from self
                if (event.data.senderId === this.tabId) {
                    return;
                }

                logger.debug('[TabSync] Received message:', event.data.type, event.data);

                // Notify all handlers
                this.handlers.forEach(handler => {
                    try {
                        handler(event.data);
                    } catch (error) {
                        logger.error('[TabSync] Handler error:', error);
                    }
                });
            };

            this.channel.onmessageerror = (event) => {
                logger.error('[TabSync] Message error:', event);
            };

            logger.info(`[TabSync] Initialized with tab ID: ${this.tabId.substring(0, 8)}...`);
        } catch (error) {
            logger.error('[TabSync] Failed to initialize BroadcastChannel:', error);
            this.isSupported = false;
        }
    }

    /**
     * Get the unique ID of this tab
     */
    getTabId(): string {
        return this.tabId;
    }

    /**
     * Check if cross-tab sync is supported
     */
    isSyncSupported(): boolean {
        return this.isSupported;
    }

    /**
     * Subscribe to sync messages
     * 
     * @param handler - Function to call when a sync message is received
     * @returns Unsubscribe function
     */
    subscribe(handler: TabSyncHandler): () => void {
        this.handlers.add(handler);
        return () => {
            this.handlers.delete(handler);
        };
    }

    /**
     * Broadcast a message to other tabs
     * 
     * @param message - Message to broadcast (without senderId and timestamp)
     */
    private broadcastMessage(message: Record<string, unknown>): void {
        if (!this.isSupported || !this.channel) {
            return;
        }

        const fullMessage = {
            ...message,
            senderId: this.tabId,
            timestamp: Date.now(),
        };

        try {
            this.channel.postMessage(fullMessage);
            logger.debug('[TabSync] Broadcast message:', message.type);
        } catch (error) {
            logger.error('[TabSync] Broadcast error:', error);
        }
    }

    /**
     * Broadcast user message sent event
     */
    broadcastUserMessageSent(conversationId: string, messageId: string, content: string): void {
        this.broadcastMessage({
            type: 'USER_MESSAGE_SENT',
            conversationId,
            messageId,
            content,
        });
    }

    /**
     * Broadcast streaming state change
     */
    broadcastStreamingStateChanged(
        conversationId: string,
        isStreaming: boolean,
        streamStatus: 'idle' | 'connecting' | 'streaming' | 'error'
    ): void {
        this.broadcastMessage({
            type: 'STREAMING_STATE_CHANGED',
            conversationId,
            isStreaming,
            streamStatus,
        });
    }

    /**
     * Broadcast conversation completed
     */
    broadcastConversationCompleted(conversationId: string): void {
        this.broadcastMessage({
            type: 'CONVERSATION_COMPLETED',
            conversationId,
        });
    }

    /**
     * Broadcast HITL state change
     */
    broadcastHITLStateChanged(
        conversationId: string,
        hasPendingHITL: boolean,
        hitlType?: 'clarification' | 'decision' | 'env_var'
    ): void {
        this.broadcastMessage({
            type: 'HITL_STATE_CHANGED',
            conversationId,
            hasPendingHITL,
            hitlType,
        });
    }

    /**
     * Broadcast conversation deleted
     */
    broadcastConversationDeleted(conversationId: string): void {
        this.broadcastMessage({
            type: 'CONVERSATION_DELETED',
            conversationId,
        });
    }

    /**
     * Broadcast conversation renamed
     */
    broadcastConversationRenamed(conversationId: string, newTitle: string): void {
        this.broadcastMessage({
            type: 'CONVERSATION_RENAMED',
            conversationId,
            newTitle,
        });
    }

    /**
     * Close the channel (cleanup)
     */
    close(): void {
        if (this.channel) {
            this.channel.close();
            this.channel = null;
        }
        this.handlers.clear();
        TabSyncManager.instance = null;
        logger.info('[TabSync] Channel closed');
    }
}

// Export singleton instance getter
export const getTabSyncManager = (): TabSyncManager => TabSyncManager.getInstance();

// Export convenience functions
export const tabSync = {
    subscribe: (handler: TabSyncHandler) => getTabSyncManager().subscribe(handler),
    broadcastUserMessageSent: (conversationId: string, messageId: string, content: string) =>
        getTabSyncManager().broadcastUserMessageSent(conversationId, messageId, content),
    broadcastStreamingStateChanged: (
        conversationId: string,
        isStreaming: boolean,
        streamStatus: 'idle' | 'connecting' | 'streaming' | 'error'
    ) => getTabSyncManager().broadcastStreamingStateChanged(conversationId, isStreaming, streamStatus),
    broadcastConversationCompleted: (conversationId: string) =>
        getTabSyncManager().broadcastConversationCompleted(conversationId),
    broadcastHITLStateChanged: (
        conversationId: string,
        hasPendingHITL: boolean,
        hitlType?: 'clarification' | 'decision' | 'env_var'
    ) => getTabSyncManager().broadcastHITLStateChanged(conversationId, hasPendingHITL, hitlType),
    broadcastConversationDeleted: (conversationId: string) =>
        getTabSyncManager().broadcastConversationDeleted(conversationId),
    broadcastConversationRenamed: (conversationId: string, newTitle: string) =>
        getTabSyncManager().broadcastConversationRenamed(conversationId, newTitle),
    getTabId: () => getTabSyncManager().getTabId(),
    isSupported: () => getTabSyncManager().isSyncSupported(),
};
