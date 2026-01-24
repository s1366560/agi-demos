/**
 * WebSocket Service for Real-time Graph Updates
 *
 * Features:
 * - Auto-reconnection with exponential backoff
 * - Event-based message handling
 * - Connection status monitoring
 * - Room subscription support
 */

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

export type WebSocketEventType =
    | 'graph_update'
    | 'episode_created'
    | 'episode_updated'
    | 'episode_deleted'
    | 'entity_created'
    | 'entity_updated'
    | 'community_rebuilt'
    | 'maintenance_progress'

export interface WebSocketMessage<T = any> {
    type: WebSocketEventType
    data: T
    timestamp: string
}

export interface GraphUpdateData {
    nodes_added: number
    nodes_removed: number
    edges_added: number
    edges_removed: number
}

export interface EpisodeCreatedData {
    episode_uuid: string
    name: string
    project_id: string
}

export interface EntityUpdatedData {
    entity_uuid: string
    name: string
    changes: string[]
}

export interface CommunityRebuiltData {
    community_count: number
    timestamp: string
}

export interface MaintenanceProgressData {
    operation: 'refresh' | 'deduplicate' | 'invalidate_edges'
    status: 'started' | 'in_progress' | 'completed' | 'failed'
    progress: number // 0-100
    message: string
}

type MessageHandler<T = any> = (data: T) => void
type StatusHandler = (status: WebSocketStatus) => void

class WebSocketService {
    private ws: WebSocket | null = null
    private url: string
    private reconnectAttempts = 0
    private maxReconnectAttempts = 5
    private reconnectDelay = 1000
    private reconnectTimeout: ReturnType<typeof setTimeout> | null = null
    private isManualClose = false
    private currentStatus: WebSocketStatus = 'disconnected'

    // Event handlers
    private messageHandlers: Map<WebSocketEventType, Set<MessageHandler>> = new Map()
    private statusHandlers: Set<StatusHandler> = new Set()

    // Subscriptions
    private subscriptions: Set<string> = new Set()

    constructor() {
        // Determine WebSocket URL based on current location
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const host = import.meta.env.VITE_WS_URL || window.location.host
        this.url = `${protocol}//${host}/ws`
    }

    /**
     * Connect to WebSocket server
     */
    connect(): void {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('[WebSocket] Already connected')
            return
        }

        this.isManualClose = false
        this.setStatus('connecting')

        try {
            // Get API key from localStorage for authentication
            const apiKey = localStorage.getItem('apiKey')
            const wsUrl = apiKey ? `${this.url}?api_key=${apiKey}` : this.url

            this.ws = new WebSocket(wsUrl)

            this.ws.onopen = () => {
                console.log('[WebSocket] Connected')
                this.setStatus('connected')
                this.reconnectAttempts = 0
                this.reconnectDelay = 1000

                // Resubscribe to previous rooms
                this.resubscribe()
            }

            this.ws.onmessage = (event) => {
                try {
                    const message: WebSocketMessage = JSON.parse(event.data)
                    this.handleMessage(message)
                } catch (err) {
                    console.error('[WebSocket] Failed to parse message:', err)
                }
            }

            this.ws.onclose = (event) => {
                console.log('[WebSocket] Disconnected', event.code, event.reason)
                this.setStatus('disconnected')

                if (!this.isManualClose && this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.scheduleReconnect()
                }
            }

            this.ws.onerror = (error) => {
                console.error('[WebSocket] Error:', error)
                this.setStatus('error')
            }
        } catch (err) {
            console.error('[WebSocket] Connection error:', err)
            this.setStatus('error')
            this.scheduleReconnect()
        }
    }

    /**
     * Disconnect from WebSocket server
     */
    disconnect(): void {
        this.isManualClose = true

        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout)
            this.reconnectTimeout = null
        }

        if (this.ws) {
            this.ws.close()
            this.ws = null
        }

        this.setStatus('disconnected')
    }

    /**
     * Subscribe to a specific room (e.g., project updates)
     */
    subscribe(room: string): void {
        this.subscriptions.add(room)

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.send({
                type: 'subscribe',
                data: { room },
            })
        }
    }

    /**
     * Unsubscribe from a room
     */
    unsubscribe(room: string): void {
        this.subscriptions.delete(room)

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.send({
                type: 'unsubscribe',
                data: { room },
            })
        }
    }

    /**
     * Register a handler for a specific message type
     */
    on<T = any>(eventType: WebSocketEventType, handler: MessageHandler<T>): () => void {
        if (!this.messageHandlers.has(eventType)) {
            this.messageHandlers.set(eventType, new Set())
        }
        this.messageHandlers.get(eventType)!.add(handler as MessageHandler)

        // Return unsubscribe function
        return () => {
            const handlers = this.messageHandlers.get(eventType)
            if (handlers) {
                handlers.delete(handler as MessageHandler)
            }
        }
    }

    /**
     * Register a handler for connection status changes
     */
    onStatusChange(handler: StatusHandler): () => void {
        this.statusHandlers.add(handler)

        // Call immediately with current status
        handler(this.currentStatus)

        // Return unsubscribe function
        return () => {
            this.statusHandlers.delete(handler)
        }
    }

    /**
     * Get current connection status
     */
    getStatus(): WebSocketStatus {
        return this.currentStatus
    }

    /**
     * Check if connected
     */
    isConnected(): boolean {
        return this.ws !== null && this.ws.readyState === WebSocket.OPEN
    }

    private send(message: any): void {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message))
        }
    }

    private handleMessage(message: WebSocketMessage): void {
        const handlers = this.messageHandlers.get(message.type)
        if (handlers) {
            handlers.forEach((handler) => {
                try {
                    handler(message.data)
                } catch (err) {
                    console.error(`[WebSocket] Handler error for ${message.type}:`, err)
                }
            })
        }
    }

    private setStatus(status: WebSocketStatus): void {
        this.currentStatus = status
        this.statusHandlers.forEach((handler) => {
            try {
                handler(status)
            } catch (err) {
                console.error('[WebSocket] Status handler error:', err)
            }
        })
    }

    private scheduleReconnect(): void {
        if (this.reconnectTimeout) {
            return
        }

        this.reconnectAttempts++
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)

        console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`)

        this.reconnectTimeout = setTimeout(() => {
            this.reconnectTimeout = null
            this.connect()
        }, delay)
    }

    private resubscribe(): void {
        this.subscriptions.forEach((room) => {
            this.send({
                type: 'subscribe',
                data: { room },
            })
        })
    }
}

// Export singleton instance
export const websocketService = new WebSocketService()

// Export a React hook for easy integration
import { useEffect, useState, useCallback } from 'react'

export function useWebSocket() {
    const [status, setStatus] = useState<WebSocketStatus>(websocketService.getStatus())

    useEffect(() => {
        const unsubscribe = websocketService.onStatusChange(setStatus)
        return unsubscribe
    }, [])

    return {
        status,
        isConnected: websocketService.isConnected(),
        connect: useCallback(() => websocketService.connect(), []),
        disconnect: useCallback(() => websocketService.disconnect(), []),
        subscribe: useCallback((room: string) => websocketService.subscribe(room), []),
        unsubscribe: useCallback((room: string) => websocketService.unsubscribe(room), []),
        on: useCallback(<T = any>(eventType: WebSocketEventType, handler: MessageHandler<T>) => {
            return websocketService.on(eventType, handler)
        }, []),
    }
}

export default websocketService
