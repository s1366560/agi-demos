/**
 * IndexedDB persistence for conversation state
 * 
 * Provides persistent storage for conversation state, enabling:
 * - State recovery after page refresh
 * - Offline access to conversation history
 * - Reduced API calls for loaded conversations
 * 
 * @packageDocumentation
 */

import type { ConversationState } from '../types/conversationState';
import type { TimelineEvent } from '../types/agent';

const DB_NAME = 'memstack-agent';
const DB_VERSION = 1;
const STORE_NAME = 'conversation-states';

/**
 * Serializable version of ConversationState for IndexedDB
 * Maps are converted to arrays of entries
 */
interface SerializedConversationState {
    timeline: TimelineEvent[];
    hasEarlier: boolean;
    earliestLoadedSequence: number | null;
    isStreaming: boolean;
    streamStatus: 'idle' | 'connecting' | 'streaming' | 'error';
    streamingAssistantContent: string;
    error: string | null;
    agentState: 'idle' | 'thinking' | 'acting' | 'observing' | 'awaiting_input';
    currentThought: string;
    streamingThought: string;
    isThinkingStreaming: boolean;
    activeToolCalls: Array<[string, unknown]>;
    pendingToolsStack: string[];
    workPlan: unknown;
    isPlanMode: boolean;
    executionPlan: unknown;
    pendingClarification: unknown;
    pendingDecision: unknown;
    pendingEnvVarRequest: unknown;
    pendingPermission: unknown;
    doomLoopDetected: unknown;
    pendingHITLSummary: unknown;
    costTracking: unknown;
    // Metadata
    lastUpdated: number;
    conversationId: string;
}

let dbInstance: IDBDatabase | null = null;

/**
 * Initialize IndexedDB connection
 */
async function getDB(): Promise<IDBDatabase> {
    if (dbInstance) return dbInstance;

    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);

        request.onerror = () => {
            console.error('[ConversationDB] Failed to open database:', request.error);
            reject(request.error);
        };

        request.onsuccess = () => {
            dbInstance = request.result;
            resolve(dbInstance);
        };

        request.onupgradeneeded = (event) => {
            const db = (event.target as IDBOpenDBRequest).result;

            // Create object store for conversation states
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                const store = db.createObjectStore(STORE_NAME, { keyPath: 'conversationId' });
                store.createIndex('lastUpdated', 'lastUpdated', { unique: false });
                console.log('[ConversationDB] Created object store:', STORE_NAME);
            }
        };
    });
}

/**
 * Serialize conversation state for storage
 */
function serializeState(
    conversationId: string,
    state: Partial<ConversationState>
): SerializedConversationState {
    return {
        conversationId,
        timeline: state.timeline || [],
        hasEarlier: state.hasEarlier || false,
        earliestLoadedSequence: state.earliestLoadedSequence || null,
        isStreaming: false, // Don't persist streaming state
        streamStatus: 'idle',
        streamingAssistantContent: '',
        error: null,
        agentState: state.agentState === 'awaiting_input' ? 'awaiting_input' : 'idle', // Preserve HITL state
        currentThought: state.currentThought || '',
        streamingThought: '',
        isThinkingStreaming: false,
        activeToolCalls: state.activeToolCalls
            ? Array.from(state.activeToolCalls.entries())
            : [],
        pendingToolsStack: [],
        workPlan: state.workPlan || null,
        isPlanMode: state.isPlanMode || false,
        executionPlan: state.executionPlan || null,
        pendingClarification: state.pendingClarification || null,
        pendingDecision: state.pendingDecision || null,
        pendingEnvVarRequest: state.pendingEnvVarRequest || null,
        pendingPermission: state.pendingPermission || null,
        doomLoopDetected: state.doomLoopDetected || null,
        pendingHITLSummary: state.pendingHITLSummary || null,
        costTracking: state.costTracking || null,
        lastUpdated: Date.now(),
    };
}

/**
 * Deserialize stored state back to ConversationState
 */
function deserializeState(stored: SerializedConversationState): ConversationState {
    return {
        timeline: stored.timeline,
        hasEarlier: stored.hasEarlier,
        earliestLoadedSequence: stored.earliestLoadedSequence,
        isStreaming: stored.isStreaming,
        streamStatus: stored.streamStatus,
        streamingAssistantContent: stored.streamingAssistantContent,
        error: stored.error,
        agentState: stored.agentState,
        currentThought: stored.currentThought,
        streamingThought: stored.streamingThought,
        isThinkingStreaming: stored.isThinkingStreaming,
        activeToolCalls: new Map(stored.activeToolCalls || []) as ConversationState['activeToolCalls'],
        pendingToolsStack: stored.pendingToolsStack,
        workPlan: stored.workPlan as ConversationState['workPlan'],
        isPlanMode: stored.isPlanMode,
        executionPlan: stored.executionPlan as ConversationState['executionPlan'],
        pendingClarification: stored.pendingClarification as ConversationState['pendingClarification'],
        pendingDecision: stored.pendingDecision as ConversationState['pendingDecision'],
        pendingEnvVarRequest: stored.pendingEnvVarRequest as ConversationState['pendingEnvVarRequest'],
        pendingPermission: stored.pendingPermission as ConversationState['pendingPermission'],
        doomLoopDetected: stored.doomLoopDetected as ConversationState['doomLoopDetected'],
        pendingHITLSummary: stored.pendingHITLSummary as ConversationState['pendingHITLSummary'],
        costTracking: stored.costTracking as ConversationState['costTracking'],
    };
}

/**
 * Save conversation state to IndexedDB
 */
export async function saveConversationState(
    conversationId: string,
    state: Partial<ConversationState>
): Promise<void> {
    try {
        const db = await getDB();
        const serialized = serializeState(conversationId, state);

        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            const request = store.put(serialized);

            request.onerror = () => {
                console.error('[ConversationDB] Failed to save state:', request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                resolve();
            };
        });
    } catch (error) {
        console.error('[ConversationDB] Save error:', error);
        // Don't throw - persistence is optional
    }
}

/**
 * Load conversation state from IndexedDB
 */
export async function loadConversationState(
    conversationId: string
): Promise<ConversationState | null> {
    try {
        const db = await getDB();

        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readonly');
            const store = transaction.objectStore(STORE_NAME);
            const request = store.get(conversationId);

            request.onerror = () => {
                console.error('[ConversationDB] Failed to load state:', request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                if (request.result) {
                    resolve(deserializeState(request.result));
                } else {
                    resolve(null);
                }
            };
        });
    } catch (error) {
        console.error('[ConversationDB] Load error:', error);
        return null;
    }
}

/**
 * Delete conversation state from IndexedDB
 */
export async function deleteConversationState(conversationId: string): Promise<void> {
    try {
        const db = await getDB();

        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            const request = store.delete(conversationId);

            request.onerror = () => {
                console.error('[ConversationDB] Failed to delete state:', request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                resolve();
            };
        });
    } catch (error) {
        console.error('[ConversationDB] Delete error:', error);
    }
}

/**
 * Clear all conversation states (for logout/reset)
 */
export async function clearAllConversationStates(): Promise<void> {
    try {
        const db = await getDB();

        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            const request = store.clear();

            request.onerror = () => {
                console.error('[ConversationDB] Failed to clear states:', request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                console.log('[ConversationDB] Cleared all conversation states');
                resolve();
            };
        });
    } catch (error) {
        console.error('[ConversationDB] Clear error:', error);
    }
}

/**
 * Get all conversation IDs with pending HITL requests
 * Useful for showing indicators in conversation list
 */
export async function getConversationsWithPendingHITL(): Promise<string[]> {
    try {
        const db = await getDB();

        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readonly');
            const store = transaction.objectStore(STORE_NAME);
            const request = store.getAll();

            request.onerror = () => {
                reject(request.error);
            };

            request.onsuccess = () => {
                const states = request.result as SerializedConversationState[];
                const pendingIds = states
                    .filter(s =>
                        s.pendingClarification ||
                        s.pendingDecision ||
                        s.pendingEnvVarRequest
                    )
                    .map(s => s.conversationId);
                resolve(pendingIds);
            };
        });
    } catch (error) {
        console.error('[ConversationDB] Get pending HITL error:', error);
        return [];
    }
}

/**
 * Clean up old conversation states (older than specified days)
 */
export async function cleanupOldStates(daysOld: number = 30): Promise<number> {
    try {
        const db = await getDB();
        const cutoffTime = Date.now() - (daysOld * 24 * 60 * 60 * 1000);
        let deletedCount = 0;

        return new Promise((resolve, reject) => {
            const transaction = db.transaction([STORE_NAME], 'readwrite');
            const store = transaction.objectStore(STORE_NAME);
            const index = store.index('lastUpdated');
            const range = IDBKeyRange.upperBound(cutoffTime);
            const request = index.openCursor(range);

            request.onerror = () => {
                reject(request.error);
            };

            request.onsuccess = (event) => {
                const cursor = (event.target as IDBRequest).result;
                if (cursor) {
                    cursor.delete();
                    deletedCount++;
                    cursor.continue();
                } else {
                    console.log(`[ConversationDB] Cleaned up ${deletedCount} old states`);
                    resolve(deletedCount);
                }
            };
        });
    } catch (error) {
        console.error('[ConversationDB] Cleanup error:', error);
        return 0;
    }
}
