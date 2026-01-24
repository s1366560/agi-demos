/**
 * AgentWorkspace - Main agent workspace layout
 *
 * Complete workspace layout matching the design:
 * - Left sidebar (64px/256px): Workspace navigation
 * - Middle panel (320px): Chat history
 * - Main area: Chat content with floating input bar
 *
 * Design reference: docs/statics/project workbench/agent/
 */

import { useState, ReactNode } from 'react';
import { WorkspaceSidebar } from './WorkspaceSidebar';
import { ChatHistorySidebar, type Conversation } from './ChatHistorySidebar';
import { FloatingInputBar } from '../chat/FloatingInputBar';

export interface AgentWorkspaceProps {
  /** Currently active navigation item */
  activeNav?: 'workspaces' | 'projects' | 'memory' | 'analytics' | 'settings';
  /** Callback when nav item is clicked */
  onNavChange?: (item: string) => void;
  /** Conversations list */
  conversations?: Conversation[];
  /** Currently selected conversation ID */
  selectedConversationId?: string;
  /** Callback when conversation is selected */
  onSelectConversation?: (conversationId: string) => void;
  /** Callback when new chat is clicked */
  onNewChat?: () => void;
  /** Main content area */
  children: ReactNode;
  /** Optional search state */
  searchQuery?: string;
  /** Callback when search changes */
  onSearchChange?: (query: string) => void;
  /** User display name */
  userName?: string;
  /** Workspace/project name */
  workspaceName?: string;
  /** Project ID for navigation */
  projectId?: string;
  /** Whether agent is currently running (for input bar state) */
  isAgentRunning?: boolean;
  /** Current input value */
  inputValue?: string;
  /** Callback when input value changes */
  onInputChange?: (value: string) => void;
  /** Callback when send is clicked */
  onSend?: (message: string) => void;
  /** Callback when stop is clicked */
  onStop?: () => void;
  /** Input placeholder */
  inputPlaceholder?: string;
  /** Whether to show input bar */
  showInput?: boolean;
}

/**
 * AgentWorkspace component
 *
 * @example
 * <AgentWorkspace
 *   workspaceName="Workspace Alpha"
 *   conversations={conversations}
 *   onNewChat={() => createChat()}
 * >
 *   <ChatContent />
 * </AgentWorkspace>
 */
export function AgentWorkspace({
  activeNav = 'workspaces',
  onNavChange,
  conversations = [],
  selectedConversationId,
  onSelectConversation,
  onNewChat,
  children,
  searchQuery = '',
  onSearchChange,
  userName = 'User',
  workspaceName = 'Workspace Alpha',
  isAgentRunning = false,
  inputValue = '',
  onInputChange,
  onSend,
  onStop,
  inputPlaceholder = "Message the Agent or type '/' for commands...",
  showInput = true,
}: AgentWorkspaceProps) {
  const [workspaceCollapsed] = useState(false);
  const [historyVisible, setHistoryVisible] = useState(true);

  return (
    <div className="flex h-screen overflow-hidden bg-background-light dark:bg-background-dark text-slate-900 dark:text-white antialiased font-display">
      {/* Left: Workspace Sidebar (64px collapsed / 256px expanded) */}
      <WorkspaceSidebar
        activeItem={activeNav}
        onNavigate={onNavChange}
        userName={userName}
        collapsed={workspaceCollapsed}
      />

      {/* Middle: Chat History Panel (320px) */}
      {historyVisible && (
        <ChatHistorySidebar
          conversations={conversations}
          selectedConversationId={selectedConversationId}
          onSelectConversation={onSelectConversation}
          onNewChat={onNewChat}
          searchQuery={searchQuery}
          onSearchChange={onSearchChange}
        />
      )}

      {/* Main Chat Area */}
      <main className="flex-1 flex flex-col relative overflow-hidden">
        {/* Top Navigation Bar */}
        <header className="flex items-center justify-between px-8 py-4 bg-background-light dark:bg-background-dark border-b border-slate-200 dark:border-border-dark shrink-0">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">layers</span>
              <h2 className="text-sm font-bold tracking-tight text-slate-900 dark:text-white">
                {workspaceName}
              </h2>
            </div>
            <div className="h-4 w-px bg-slate-200 dark:bg-border-dark" />
            <nav className="flex gap-6">
              <a className="text-sm font-medium text-slate-900 dark:text-white cursor-pointer">
                Dashboard
              </a>
              <a className="text-sm font-medium text-slate-500 hover:text-slate-900 dark:text-text-muted dark:hover:text-white transition-colors cursor-pointer">
                Logs
              </a>
            </nav>
          </div>

          {/* Right side: Search and actions */}
          <div className="flex items-center gap-4">
            <div className="relative w-64">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-text-muted text-lg">
                search
              </span>
              <input
                type="text"
                className="w-full bg-slate-100 dark:bg-surface-dark border-none rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary/50 transition-all placeholder:text-text-muted"
                placeholder="Search memory..."
              />
            </div>
            <div className="flex gap-2">
              <button className="p-2 bg-slate-100 dark:bg-surface-dark rounded-lg hover:bg-slate-200 dark:hover:bg-border-dark transition-colors text-slate-600 dark:text-white">
                <span className="material-symbols-outlined text-[20px]">cloud_done</span>
              </button>
              <button className="p-2 bg-slate-100 dark:bg-surface-dark rounded-lg hover:bg-slate-200 dark:hover:bg-border-dark transition-colors text-slate-600 dark:text-white">
                <span className="material-symbols-outlined text-[20px]">insights</span>
              </button>
            </div>
          </div>
        </header>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto relative">
          {/* Gradient fade at bottom for scrolling indication */}
          <div className="px-8 py-6 pb-48">
            {children}
          </div>

          {/* Bottom gradient fade for follow-up section */}
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background-light dark:from-background-dark via-background-light/95 dark:via-background-dark/95 to-transparent pt-20 pb-10 px-8 flex flex-col items-center pointer-events-none">
            {/* Floating Input Bar */}
            {showInput && (
              <div className="pointer-events-auto">
                <FloatingInputBar
                  value={inputValue}
                  onChange={onInputChange}
                  onSend={onSend}
                  onStop={onStop}
                  disabled={isAgentRunning}
                  placeholder={isAgentRunning ? 'Agent is thinking...' : inputPlaceholder}
                />
              </div>
            )}
          </div>
        </div>
      </main>

      {/* History collapsed toggle button (visible when history is collapsed) */}
      {!historyVisible && (
        <button
          onClick={() => setHistoryVisible(true)}
          className="absolute left-0 top-1/2 -translate-y-1/2 w-8 h-16 bg-white dark:bg-surface-dark border border-r-0 rounded-r-lg shadow-lg flex items-center justify-center hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors z-10"
          title="Show chat history"
        >
          <span className="material-symbols-outlined text-slate-500">chevron_right</span>
        </button>
      )}
    </div>
  );
}

export default AgentWorkspace;
