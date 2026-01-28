import React from "react";
import { Layout, Button } from "antd";
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { useAgentV3Store } from "../../stores/agentV3";

const { Sider, Content } = Layout;

interface ChatLayoutProps {
  sidebar: React.ReactNode;
  chatArea: React.ReactNode;
  /** Right panel content (Plan + Sandbox tabs) */
  rightPanel: React.ReactNode;
  /** @deprecated Use rightPanel instead */
  planPanel?: React.ReactNode;
}

export const ChatLayout: React.FC<ChatLayoutProps> = ({
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
  const panelContent = rightPanel || planPanel;

  return (
    <Layout className="h-full bg-white">
      {/* Left Sidebar (History) */}
      <Sider
        width={280}
        theme="light"
        collapsedWidth={0}
        collapsed={!showHistorySidebar}
        trigger={null}
        className="border-r border-slate-200"
      >
        <div className="flex flex-col h-full">{sidebar}</div>
      </Sider>

      {/* Main Content */}
      <Layout className="bg-white">
        <Content className="flex flex-col h-full relative">
          {/* Header / Toolbar Overlay (Absolute or Flex) */}
          <div className="absolute top-4 left-4 z-10">
            <Button
              icon={
                showHistorySidebar ? (
                  <MenuFoldOutlined />
                ) : (
                  <MenuUnfoldOutlined />
                )
              }
              onClick={toggleHistorySidebar}
              type="text"
              className="bg-white/80 backdrop-blur shadow-sm border border-slate-200"
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
        className="border-l border-slate-200"
      >
        {panelContent}
      </Sider>
    </Layout>
  );
};
