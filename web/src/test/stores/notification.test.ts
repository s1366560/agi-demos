import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useNotificationStore } from '../../stores/notification'

// Mock the API module
// Note: httpClient.get already returns response.data, so mock should return the data directly
vi.mock('../../services/api', () => ({
    default: {
        get: vi.fn().mockResolvedValue({ notifications: [] }),
        put: vi.fn().mockResolvedValue({}),
        delete: vi.fn().mockResolvedValue({}),
    },
}))

describe('Notification Store', () => {
  beforeEach(() => {
    // Reset store state before each test
    useNotificationStore.setState({
      notifications: [],
      unreadCount: 0,
      isLoading: false,
    })
  })

  describe('initial state', () => {
    it('should have correct initial state', () => {
      const state = useNotificationStore.getState()
      expect(state.notifications).toEqual([])
      expect(state.unreadCount).toBe(0)
      expect(state.isLoading).toBe(false)
    })
  })

  describe('fetchNotifications', () => {
    it('should fetch notifications successfully', async () => {
      const api = (await import('../../services/api')).default
      const mockNotifications = [
        {
          id: '1',
          type: 'info',
          title: 'Test',
          message: 'Test message',
          data: {},
          is_read: false,
          created_at: '2024-01-01T00:00:00Z',
        },
        {
          id: '2',
          type: 'warning',
          title: 'Test 2',
          message: 'Test message 2',
          data: {},
          is_read: true,
          created_at: '2024-01-01T00:00:00Z',
        },
      ]

      // api.get returns response.data directly, so mock should return the data structure
      vi.mocked(api.get).mockResolvedValue({
        notifications: mockNotifications,
      })

      const { fetchNotifications } = useNotificationStore.getState()

      await fetchNotifications()

      const state = useNotificationStore.getState()
      expect(state.notifications).toEqual(mockNotifications)
      expect(state.unreadCount).toBe(1)
      expect(state.isLoading).toBe(false)
      expect(api.get).toHaveBeenCalledWith('/notifications/', {
        params: { unread_only: false },
      })
    })

    it('should fetch unread only notifications', async () => {
      const api = (await import('../../services/api')).default
      const mockNotifications = [
        {
          id: '1',
          type: 'info',
          title: 'Test',
          message: 'Test message',
          data: {},
          is_read: false,
          created_at: '2024-01-01T00:00:00Z',
        },
      ]

      // api.get returns response.data directly, so mock should return the data structure
      vi.mocked(api.get).mockResolvedValue({
        notifications: mockNotifications,
      })

      const { fetchNotifications } = useNotificationStore.getState()

      await fetchNotifications(true)

      expect(api.get).toHaveBeenCalledWith('/notifications/', {
        params: { unread_only: true },
      })
    })

    it('should handle fetch errors gracefully', async () => {
      const api = (await import('../../services/api')).default
      vi.mocked(api.get).mockRejectedValue(new Error('Network error'))

      const { fetchNotifications } = useNotificationStore.getState()
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      await fetchNotifications()

      const state = useNotificationStore.getState()
      expect(state.notifications).toEqual([])
      expect(state.isLoading).toBe(false)
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })

    it('should set loading state during fetch', async () => {
      const api = (await import('../../services/api')).default

      // Create a promise that we can control
      let resolveFetch: () => void
      const fetchPromise = new Promise<void>((resolve) => {
        resolveFetch = resolve
      })

      vi.mocked(api.get).mockImplementation(() => fetchPromise)

      const { fetchNotifications } = useNotificationStore.getState()

      // Start fetch (loading should be true)
      const fetchCall = fetchNotifications()
      expect(useNotificationStore.getState().isLoading).toBe(true)

      // Resolve and wait
      resolveFetch!()
      vi.mocked(api.get).mockResolvedValue({ data: { notifications: [] } })
      await fetchCall

      expect(useNotificationStore.getState().isLoading).toBe(false)
    })
  })

  describe('markAsRead', () => {
    it('should mark notification as read successfully', async () => {
      const api = (await import('../../services/api')).default
      // api.put returns response.data directly
      vi.mocked(api.put).mockResolvedValue({ success: true })

      // Set initial state with unread notification
      useNotificationStore.setState({
        notifications: [
          {
            id: '1',
            type: 'info',
            title: 'Test',
            message: 'Test',
            data: {},
            is_read: false,
            created_at: '2024-01-01T00:00:00Z',
          },
        ],
        unreadCount: 1,
      })

      const { markAsRead } = useNotificationStore.getState()

      await markAsRead('1')

      const state = useNotificationStore.getState()
      expect(state.notifications[0].is_read).toBe(true)
      expect(state.unreadCount).toBe(0)
      expect(api.put).toHaveBeenCalledWith('/notifications/1/read')
    })

    it('should handle markAsRead errors gracefully', async () => {
      const api = (await import('../../services/api')).default
      vi.mocked(api.put).mockRejectedValue(new Error('Network error'))

      useNotificationStore.setState({
        notifications: [
          {
            id: '1',
            type: 'info',
            title: 'Test',
            message: 'Test',
            data: {},
            is_read: false,
            created_at: '2024-01-01T00:00:00Z',
          },
        ],
        unreadCount: 1,
      })

      const { markAsRead } = useNotificationStore.getState()
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      await markAsRead('1')

      // State should remain unchanged on error
      const state = useNotificationStore.getState()
      expect(state.notifications[0].is_read).toBe(false)
      expect(state.unreadCount).toBe(1)
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })
  })

  describe('markAllAsRead', () => {
    it('should mark all notifications as read successfully', async () => {
      const api = (await import('../../services/api')).default
      // api.put returns response.data directly
      vi.mocked(api.put).mockResolvedValue({
        success: true,
        count: 2,
      })

      useNotificationStore.setState({
        notifications: [
          {
            id: '1',
            type: 'info',
            title: 'Test',
            message: 'Test',
            data: {},
            is_read: false,
            created_at: '2024-01-01T00:00:00Z',
          },
          {
            id: '2',
            type: 'warning',
            title: 'Test 2',
            message: 'Test 2',
            data: {},
            is_read: false,
            created_at: '2024-01-01T00:00:00Z',
          },
        ],
        unreadCount: 2,
      })

      const { markAllAsRead } = useNotificationStore.getState()

      await markAllAsRead()

      const state = useNotificationStore.getState()
      expect(state.notifications.every((n) => n.is_read)).toBe(true)
      expect(state.unreadCount).toBe(0)
      expect(api.put).toHaveBeenCalledWith('/notifications/read-all')
    })

    it('should handle markAllAsRead errors gracefully', async () => {
      const api = (await import('../../services/api')).default
      vi.mocked(api.put).mockRejectedValue(new Error('Network error'))

      const initialState = [
        {
          id: '1',
          type: 'info',
          title: 'Test',
          message: 'Test',
          data: {},
          is_read: false,
          created_at: '2024-01-01T00:00:00Z',
        },
      ]

      useNotificationStore.setState({
        notifications: initialState,
        unreadCount: 1,
      })

      const { markAllAsRead } = useNotificationStore.getState()
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      await markAllAsRead()

      // State should remain unchanged on error
      const state = useNotificationStore.getState()
      expect(state.notifications).toEqual(initialState)
      expect(state.unreadCount).toBe(1)
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })
  })

  describe('deleteNotification', () => {
    it('should delete notification successfully', async () => {
      const api = (await import('../../services/api')).default
      // api.delete returns response.data directly
      vi.mocked(api.delete).mockResolvedValue({ success: true })

      useNotificationStore.setState({
        notifications: [
          {
            id: '1',
            type: 'info',
            title: 'Test',
            message: 'Test',
            data: {},
            is_read: false,
            created_at: '2024-01-01T00:00:00Z',
          },
          {
            id: '2',
            type: 'warning',
            title: 'Test 2',
            message: 'Test 2',
            data: {},
            is_read: true,
            created_at: '2024-01-01T00:00:00Z',
          },
        ],
        unreadCount: 1,
      })

      const { deleteNotification } = useNotificationStore.getState()

      await deleteNotification('1')

      const state = useNotificationStore.getState()
      expect(state.notifications).toHaveLength(1)
      expect(state.notifications[0].id).toBe('2')
      expect(state.unreadCount).toBe(0)
      expect(api.delete).toHaveBeenCalledWith('/notifications/1')
    })

    it('should decrease unread count when deleting unread notification', async () => {
      const api = (await import('../../services/api')).default
      // api.delete returns response.data directly
      vi.mocked(api.delete).mockResolvedValue({ success: true })

      useNotificationStore.setState({
        notifications: [
          {
            id: '1',
            type: 'info',
            title: 'Test',
            message: 'Test',
            data: {},
            is_read: false,
            created_at: '2024-01-01T00:00:00Z',
          },
        ],
        unreadCount: 1,
      })

      const { deleteNotification } = useNotificationStore.getState()

      await deleteNotification('1')

      const state = useNotificationStore.getState()
      expect(state.unreadCount).toBe(0)
    })

    it('should not decrease unread count when deleting read notification', async () => {
      const api = (await import('../../services/api')).default
      // api.delete returns response.data directly
      vi.mocked(api.delete).mockResolvedValue({ success: true })

      useNotificationStore.setState({
        notifications: [
          {
            id: '1',
            type: 'info',
            title: 'Test',
            message: 'Test',
            data: {},
            is_read: true,
            created_at: '2024-01-01T00:00:00Z',
          },
        ],
        unreadCount: 0,
      })

      const { deleteNotification } = useNotificationStore.getState()

      await deleteNotification('1')

      const state = useNotificationStore.getState()
      expect(state.unreadCount).toBe(0)
    })

    it('should handle delete errors gracefully', async () => {
      const api = (await import('../../services/api')).default
      vi.mocked(api.delete).mockRejectedValue(new Error('Network error'))

      const initialState = [
        {
          id: '1',
          type: 'info',
          title: 'Test',
          message: 'Test',
          data: {},
          is_read: false,
          created_at: '2024-01-01T00:00:00Z',
        },
      ]

      useNotificationStore.setState({
        notifications: initialState,
        unreadCount: 1,
      })

      const { deleteNotification } = useNotificationStore.getState()
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      await deleteNotification('1')

      // State should remain unchanged on error
      const state = useNotificationStore.getState()
      expect(state.notifications).toEqual(initialState)
      expect(state.unreadCount).toBe(1)
      expect(consoleSpy).toHaveBeenCalled()

      consoleSpy.mockRestore()
    })
  })
})
