import React, { memo, useMemo, useCallback } from "react";
import { Layout, Button } from "antd";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { useAgentV3Store } from "../../stores/agentV3";

const { Sider, Content } = Layout;

/**
 * Props for ChatLayout component
 */
interface ChatLayoutProps {
  /** Left sidebar content (conversation history) */
  sidebar: React.ReactNode;
  /** Main chat area content */
  chatArea: React.ReactNode;
  /** Right panel content (Plan + Sandbox tabs) */
  rightPanel: React.ReactNode;
  /** @deprecated Use rightPanel instead - legacy plan panel */
  planPanel?: React.ReactNode;
}

/**
 * ChatLayout Component - Three-panel layout for agent chat interface
 *
 * Provides a responsive three-panel layout with collapsible sidebars.
 * Manages left sidebar (conversation history) and right panel (plan/sandbox)
 * visibility state through the agent store.
 *
 * @component
 *
 * @features
 * - Collapsible left sidebar (280px) for conversation history
 * - Collapsible right panel (400px) for execution details
 * - Floating toggle button for sidebar visibility
 * - Memoized handlers to prevent unnecessary re-renders
 * - Responsive layout with Ant Design Layout components
 *
 * @example
 * ```tsx
 * import { ChatLayout } from '@/components/agent/ChatLayout'
 *
 * function AgentChat() {
 *   return (
 *     <ChatLayout
 *       sidebar={<ConversationList />}
 *       chatArea={<MessageArea />}
 *       rightPanel={<ExecutionPanel />}
 *     />
 *   )
 * }
 * ```
 */

export const ChatLayout: React.FC<ChatLayoutProps> = memo(({
  sidebar,
  chatArea,
  rightPanel,
  planPanel,
}) => {
  const {
    showPlanPanel,
    showHistorySidebar,
    toggleHistorySidebar,
  } = useAgentV3Store();

  // Support both rightPanel and legacy planPanel prop
  const panelContent = useMemo(() => rightPanel || planPanel, [rightPanel, planPanel]);

  // Memoize the toggle handler to prevent re-creation on every render
  const handleToggleSidebar = useCallback(() => {
    toggleHistorySidebar();
  }, [toggleHistorySidebar]);

  // Memoize the icon to prevent re-creation on every render
  const sidebarIcon = useMemo(() => {
    return showHistorySidebar ? <MenuFoldOutlined /> : <MenuUnfoldOutlined />;
  }, [showHistorySidebar]);

  return (
    <Layout className="h-full bg-slate-50">
      {/* Left Sidebar (History) */}
      <Sider
        width={280}
        theme="light"
        collapsedWidth={0}
        collapsed={!showHistorySidebar}
        trigger={null}
        className="border-r border-slate-200 bg-white shadow-sm z-20"
        style={{ overflow: 'hidden' }}
      >
        <div className="flex flex-col h-full">{sidebar}</div>
      </Sider>

      {/* Main Content */}
      <Layout className="bg-transparent">
        <Content className="flex flex-col h-full relative bg-gradient-to-br from-slate-50 to-white">
          {/* Header / Toolbar Overlay with improved spacing */}
          <div className="absolute top-4 left-4 z-30">
            <Button
              icon={sidebarIcon}
              onClick={handleToggleSidebar}
              type="text"
              size="large"
              className="bg-white/90 backdrop-blur-md shadow-md border border-slate-200/60 hover:shadow-lg hover:border-primary/30 transition-all duration-200 rounded-xl"
              aria-label={showHistorySidebar ? "Hide conversation history" : "Show conversation history"}
            />
          </div>

          {chatArea}
        </Content>
      </Layout>

      {/* Right Sidebar (Plan + Sandbox) */}
      <Sider
        width={400}
        theme="light"
        collapsedWidth={0}
        collapsed={!showPlanPanel}
        trigger={null}
        className="border-l border-slate-200 bg-white shadow-sm z-20"
        style={{ overflow: 'auto' }}
      >
        {panelContent}
      </Sider>
    </Layout>
  );
});

ChatLayout.displayName = 'ChatLayout';
