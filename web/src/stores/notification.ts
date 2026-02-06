import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  data: Record<string, unknown>;
  is_read: boolean;
  action_url?: string;
  created_at: string;
  expires_at?: string;
}

interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  isLoading: boolean;

  fetchNotifications: (unreadOnly?: boolean) => Promise<void>;
  markAsRead: (id: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  deleteNotification: (id: string) => Promise<void>;
}

interface NotificationsResponse {
  notifications: Notification[];
}

export const useNotificationStore = create<NotificationState>()(
  devtools(
    (set, get) => ({
      notifications: [],
      unreadCount: 0,
      isLoading: false,

      fetchNotifications: async (unreadOnly = false) => {
        set({ isLoading: true });
        try {
          const api = (await import('../services/api')).default;
          const response = await api.get<NotificationsResponse>('/notifications/', {
            params: { unread_only: unreadOnly },
          });
          const notificationsList = response.notifications;

          set({
            notifications: notificationsList,
            unreadCount: notificationsList.filter((n: Notification) => !n.is_read).length,
            isLoading: false,
          });
        } catch (error) {
          console.error('Failed to fetch notifications:', error);
          set({ isLoading: false });
        }
      },

      markAsRead: async (id: string) => {
        try {
          const api = (await import('../services/api')).default;
          await api.put(`/notifications/${id}/read`);

          const { notifications } = get();
          set({
            notifications: notifications.map((n) => (n.id === id ? { ...n, is_read: true } : n)),
            unreadCount: Math.max(0, get().unreadCount - 1),
          });
        } catch (error) {
          console.error('Failed to mark notification as read:', error);
        }
      },

      markAllAsRead: async () => {
        try {
          const api = (await import('../services/api')).default;
          await api.put('/notifications/read-all');

          const { notifications } = get();
          set({
            notifications: notifications.map((n) => ({ ...n, is_read: true })),
            unreadCount: 0,
          });
        } catch (error) {
          console.error('Failed to mark all as read:', error);
        }
      },

      deleteNotification: async (id: string) => {
        try {
          const api = (await import('../services/api')).default;
          await api.delete(`/notifications/${id}`);

          const { notifications } = get();
          const notification = notifications.find((n) => n.id === id);
          set({
            notifications: notifications.filter((n) => n.id !== id),
            unreadCount:
              notification && !notification.is_read ? get().unreadCount - 1 : get().unreadCount,
          });
        } catch (error) {
          console.error('Failed to delete notification:', error);
        }
      },
    }),
    {
      name: 'NotificationStore',
      enabled: import.meta.env.DEV,
    }
  )
);
