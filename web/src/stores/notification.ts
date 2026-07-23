import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

import api from '../services/api';

interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  data: Record<string, unknown>;
  is_read: boolean;
  action_url?: string | undefined;
  created_at: string;
  expires_at?: string | undefined;
}

interface NotificationState {
  notifications: Notification[];
  unreadCount: number;
  isLoading: boolean;
  /** True when the last fetch failed; cleared on the next successful fetch. */
  error: boolean;

  fetchNotifications: (unreadOnly?: boolean) => Promise<void>;
  markAsRead: (id: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  deleteNotification: (id: string) => Promise<void>;
}

interface NotificationsResponse {
  notifications: Notification[];
}

let latestFetchNotificationsRequest = 0;

export const useNotificationStore = create<NotificationState>()(
  devtools(
    (set, get) => ({
      notifications: [],
      unreadCount: 0,
      isLoading: false,
      error: false,

      fetchNotifications: async (unreadOnly = false) => {
        const requestId = latestFetchNotificationsRequest + 1;
        latestFetchNotificationsRequest = requestId;
        set({ isLoading: true });
        try {
          const response = await api.get<NotificationsResponse>('/notifications/', {
            params: { unread_only: unreadOnly },
          });
          if (requestId !== latestFetchNotificationsRequest) return;
          const notificationsList = response.notifications;

          set({
            notifications: notificationsList,
            unreadCount: notificationsList.filter((n: Notification) => !n.is_read).length,
            isLoading: false,
            error: false,
          });
        } catch (error) {
          if (requestId !== latestFetchNotificationsRequest) return;
          console.error('Failed to fetch notifications:', error);
          set({ isLoading: false, error: true });
        }
      },

      markAsRead: async (id: string) => {
        try {
          await api.put(`/notifications/${id}/read`);

          const { notifications, unreadCount } = get();
          const notification = notifications.find((n) => n.id === id);
          set({
            notifications: notifications.map((n) => (n.id === id ? { ...n, is_read: true } : n)),
            unreadCount:
              notification && !notification.is_read ? Math.max(0, unreadCount - 1) : unreadCount,
          });
        } catch (error) {
          console.error('Failed to mark notification as read:', error);
        }
      },

      markAllAsRead: async () => {
        try {
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
