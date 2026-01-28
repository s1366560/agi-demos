import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Bell, X, Check, Trash2, Loader2 } from 'lucide-react';
import { useNotificationStore } from '@/stores/notification';
import { useNavigate } from 'react-router-dom';

export const NotificationPanel: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const { notifications, unreadCount, fetchNotifications, markAsRead, markAllAsRead, deleteNotification, isLoading } = useNotificationStore();
  const navigate = useNavigate();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchNotifications(true);

    // Poll for new notifications every 30 seconds
    const interval = setInterval(() => fetchNotifications(true), 30000);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  useEffect(() => {
    // Close panel when clicking outside
    const handleClickOutside = (event: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
    return undefined;
  }, [isOpen]);

  // Stable callback for notification clicks
  const handleNotificationClick = useCallback(async (notification: any) => {
    if (!notification.is_read) {
      await markAsRead(notification.id);
    }
    if (notification.action_url) {
      navigate(notification.action_url);
      setIsOpen(false);
    }
  }, [markAsRead, navigate]);

  // Stable callback for toggling panel
  const togglePanel = useCallback(() => {
    setIsOpen(prev => !prev);
  }, []);

  // Stable callback for closing panel
  const closePanel = useCallback(() => {
    setIsOpen(false);
  }, []);

  // Stable callback for inline mark as read
  const handleInlineMarkAsRead = useCallback((e: React.MouseEvent, notificationId: string) => {
    e.stopPropagation();
    markAsRead(notificationId);
  }, [markAsRead]);

  // Stable callback for inline delete
  const handleInlineDelete = useCallback((e: React.MouseEvent, notificationId: string) => {
    e.stopPropagation();
    deleteNotification(notificationId);
  }, [deleteNotification]);

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={togglePanel}
        className="relative p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        title="通知"
      >
        <Bell className="w-5 h-5 text-gray-600 dark:text-slate-400" />
        {unreadCount > 0 && (
          <span className="absolute top-0 right-0 h-5 w-5 bg-red-500 rounded-full text-white text-xs flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 top-12 w-96 bg-white dark:bg-slate-900 rounded-lg shadow-xl border border-slate-200 dark:border-slate-800 z-50">
          <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <h3 className="font-semibold text-slate-900 dark:text-white">通知</h3>
            <div className="flex items-center gap-2">
              {unreadCount > 0 && (
                <button
                  onClick={markAllAsRead}
                  className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  全部已读
                </button>
              )}
              <button onClick={closePanel}><X className="w-4 h-4" /></button>
            </div>
          </div>

          <div className="max-h-96 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-8 w-8 animate-spin text-blue-600 dark:text-blue-400" />
              </div>
            ) : notifications.length === 0 ? (
              <div className="p-8 text-center text-slate-500 dark:text-slate-400">
                <Bell className="h-12 w-12 mx-auto mb-2 opacity-50" />
                <p>暂无通知</p>
              </div>
            ) : (
              notifications.map((notification) => (
                <div
                  key={notification.id}
                  className={`p-4 border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer ${
                    !notification.is_read ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                  }`}
                  onClick={() => handleNotificationClick(notification)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <p className="font-medium text-sm text-slate-900 dark:text-white">{notification.title}</p>
                      <p className="text-xs text-slate-600 dark:text-slate-400 mt-1">{notification.message}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-500 mt-1">
                        {new Date(notification.created_at).toLocaleString('zh-CN')}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 ml-2">
                      {!notification.is_read && (
                        <button
                          onClick={(e) => handleInlineMarkAsRead(e, notification.id)}
                          className="p-1 hover:bg-slate-200 dark:hover:bg-slate-700 rounded"
                          title="标记为已读"
                        >
                          <Check className="w-3 h-3 text-green-600 dark:text-green-400" />
                        </button>
                      )}
                      <button
                        onClick={(e) => handleInlineDelete(e, notification.id)}
                        className="p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded"
                        title="删除"
                      >
                        <Trash2 className="w-3 h-3 text-red-600 dark:text-red-400" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
};
