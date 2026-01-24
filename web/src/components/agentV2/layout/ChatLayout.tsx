/**
 * Chat Layout
 *
 * Main layout component for Agent Chat interface.
 * Provides the overall structure with sidebar and main chat area.
 */

import { type ReactNode } from "react";

interface ChatLayoutProps {
  children: ReactNode;
  sidebar?: ReactNode;
}

export function ChatLayout({ children, sidebar }: ChatLayoutProps) {
  return (
    <div className="flex h-screen bg-white dark:bg-gray-900">
      {/* Sidebar */}
      {sidebar && (
        <aside className="w-72 flex-shrink-0 border-r border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950">
          {sidebar}
        </aside>
      )}

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0">{children}</main>
    </div>
  );
}
