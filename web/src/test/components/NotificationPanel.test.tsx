import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// Mock the notification store first, before importing the component
const mockFetchNotifications = vi.fn()
const mockMarkAsRead = vi.fn(() => Promise.resolve())
const mockMarkAllAsRead = vi.fn(() => Promise.resolve())
const mockDeleteNotification = vi.fn(() => Promise.resolve())

// Mock store state
const mockStoreState = {
  notifications: [] as any[],
  unreadCount: 0,
  isLoading: false,
  fetchNotifications: mockFetchNotifications,
  markAsRead: mockMarkAsRead,
  markAllAsRead: mockMarkAllAsRead,
  deleteNotification: mockDeleteNotification,
}

vi.mock('../../stores/notification', () => ({
  useNotificationStore: vi.fn(() => mockStoreState),
}))

// Mock react-router-dom
const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

// Import component after mocks are set up
import { NotificationPanel } from '../../components/NotificationPanel'

describe('NotificationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()

    // Reset mock store state
    mockStoreState.notifications = []
    mockStoreState.unreadCount = 0
    mockStoreState.isLoading = false
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('rendering', () => {
    it('should render bell icon', () => {
      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      expect(bellButton).toBeInTheDocument()
    })

    it('should not show unread badge when unreadCount is 0', () => {
      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      expect(bellButton.textContent).not.toContain('+')
    })

    it('should show unread count badge when unreadCount > 0', () => {
      mockStoreState.unreadCount = 3

      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: '3' })
      expect(bellButton).toBeInTheDocument()
      expect(bellButton.textContent).toContain('3')
    })

    it('should show 9+ when unreadCount > 9', () => {
      mockStoreState.unreadCount = 15

      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: '9+' })
      expect(bellButton).toBeInTheDocument()
      expect(bellButton.textContent).toContain('9+')
    })
  })

  describe('panel open/close', () => {
    it('should open panel when bell icon is clicked', () => {
      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      fireEvent.click(bellButton)

      expect(screen.getByText('通知')).toBeInTheDocument()
    })

    it('should close panel when X button is clicked', () => {
      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      fireEvent.click(bellButton)

      // Get all buttons, the close button is the second one
      const buttons = screen.getAllByRole('button')
      const closeButton = buttons.find(btn => btn.querySelector('svg.lucide-x'))
      fireEvent.click(closeButton!)

      // Panel should be closed
      expect(screen.queryByText('通知')).not.toBeInTheDocument()
    })

    it('should close panel when clicking outside', () => {
      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      fireEvent.click(bellButton)

      // Verify panel is open
      expect(screen.getByText('通知')).toBeInTheDocument()

      // Click outside the panel
      fireEvent.mouseDown(document.body)

      // Panel should be closed immediately (synchronous in this case)
      expect(screen.queryByText('通知')).not.toBeInTheDocument()
    })
  })

  describe('notifications list', () => {
    it('should show loading spinner when isLoading is true', () => {
      mockStoreState.isLoading = true

      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      fireEvent.click(bellButton)

      // Check for the loading spinner container
      const loadingContainer = screen.getByText('通知').closest('div')?.nextElementSibling?.querySelector('[class*="animate-spin"]')
      expect(loadingContainer).toBeInTheDocument()
    })

    it('should show empty state when no notifications', () => {
      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      fireEvent.click(bellButton)

      expect(screen.getByText('暂无通知')).toBeInTheDocument()
    })

    it('should render notifications list', () => {
      const mockNotifications = [
        {
          id: '1',
          type: 'info',
          title: 'Test Notification',
          message: 'Test message',
          data: {},
          is_read: false,
          created_at: '2024-01-01T00:00:00Z',
        },
        {
          id: '2',
          type: 'warning',
          title: 'Test Notification 2',
          message: 'Test message 2',
          data: {},
          is_read: true,
          created_at: '2024-01-01T01:00:00Z',
        },
      ]

      mockStoreState.notifications = mockNotifications
      mockStoreState.unreadCount = 1

      render(<NotificationPanel />)

      // Find bell button by title since it has a badge
      const bellButton = screen.getByTitle('通知')
      fireEvent.click(bellButton)

      expect(screen.getByText('Test Notification')).toBeInTheDocument()
      expect(screen.getByText('Test message')).toBeInTheDocument()
      expect(screen.getByText('Test Notification 2')).toBeInTheDocument()
    })

    it('should show mark all as read button when there are unread notifications', () => {
      mockStoreState.notifications = [
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
      mockStoreState.unreadCount = 1

      render(<NotificationPanel />)

      // Find bell button by title since it has a badge
      const bellButton = screen.getByTitle('通知')
      fireEvent.click(bellButton)

      expect(screen.getByText('全部已读')).toBeInTheDocument()
    })
  })

  describe('notification interactions', () => {
    it('should call markAsRead when clicking unread notification', async () => {
      const mockNotifications = [
        {
          id: '1',
          type: 'info',
          title: 'Test',
          message: 'Test',
          data: {},
          is_read: false,
          created_at: '2024-01-01T00:00:00Z',
          action_url: '/projects/123',
        },
      ]

      mockStoreState.notifications = mockNotifications
      mockStoreState.unreadCount = 1

      // Use real timers for this test to avoid timeout issues
      vi.useRealTimers()

      render(<NotificationPanel />)

      const bellButton = screen.getByTitle('通知')
      fireEvent.click(bellButton)

      // Click on the notification div (the container) using the first "Test" text (the title)
      const testElements = screen.getAllByText('Test')
      const notificationDiv = testElements[0].closest('.p-4')
      fireEvent.click(notificationDiv!)

      // Wait for async operations to complete
      await waitFor(() => {
        expect(mockMarkAsRead).toHaveBeenCalledWith('1')
      })
      expect(mockNavigate).toHaveBeenCalledWith('/projects/123')
    })

    it('should call deleteNotification when delete button is clicked', () => {
      const mockNotifications = [
        {
          id: '1',
          type: 'info',
          title: 'Test',
          message: 'Test',
          data: {},
          is_read: true,
          created_at: '2024-01-01T00:00:00Z',
        },
      ]

      mockStoreState.notifications = mockNotifications

      render(<NotificationPanel />)

      const bellButton = screen.getByRole('button', { name: /通知/i })
      fireEvent.click(bellButton)

      const deleteButtons = screen.getAllByTitle('删除')
      fireEvent.click(deleteButtons[0])

      // The delete is async but we just check that it was called
      // The mock function will capture the call
      expect(mockDeleteNotification).toHaveBeenCalledWith('1')
    })

    it('should call markAllAsRead when clicking mark all as read button', () => {
      mockStoreState.notifications = [
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
      mockStoreState.unreadCount = 1

      render(<NotificationPanel />)

      const bellButton = screen.getByTitle('通知')
      fireEvent.click(bellButton)

      const markAllButton = screen.getByText('全部已读')
      fireEvent.click(markAllButton)

      expect(mockMarkAllAsRead).toHaveBeenCalled()
    })
  })

  describe('initialization', () => {
    it('should fetch notifications on mount', () => {
      render(<NotificationPanel />)

      expect(mockFetchNotifications).toHaveBeenCalledWith(true)
    })

    it('should poll for notifications every 30 seconds', () => {
      render(<NotificationPanel />)

      // Initial call
      expect(mockFetchNotifications).toHaveBeenCalledWith(true)

      // Fast-forward 30 seconds
      vi.advanceTimersByTime(30000)

      expect(mockFetchNotifications).toHaveBeenCalledTimes(2)
    })

    it('should cleanup polling on unmount', () => {
      const { unmount } = render(<NotificationPanel />)

      unmount()

      // Fast-forward - should not call fetchNotifications
      vi.advanceTimersByTime(30000)

      // Should still be 1 (only initial call)
      expect(mockFetchNotifications).toHaveBeenCalledTimes(1)
    })
  })
})
