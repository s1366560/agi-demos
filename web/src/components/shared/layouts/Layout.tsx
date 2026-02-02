import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  AppstoreOutlined,
  DatabaseOutlined,
  SearchOutlined,
  PartitionOutlined,
  SettingOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { LazyMenu } from '@/components/ui/lazyAntd';
import { Layout as AntLayout } from 'antd';
import type { MenuProps } from 'antd';

const { Header, Content, Sider } = AntLayout;

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  const menuItems: MenuProps['items'] = [
    {
      key: '/',
      icon: <AppstoreOutlined />,
      label: <Link to="/">Dashboard</Link>,
    },
    {
      key: '/episodes',
      icon: <DatabaseOutlined />,
      label: <Link to="/episodes">Episodes</Link>,
    },
    {
      key: '/search',
      icon: <SearchOutlined />,
      label: <Link to="/search">Search</Link>,
    },
    {
      key: '/graph',
      icon: <PartitionOutlined />,
      label: <Link to="/graph">Knowledge Graph</Link>,
    },
    {
      key: '/memos',
      icon: <FileTextOutlined />,
      label: <Link to="/memos">Memos</Link>,
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: <Link to="/settings">Settings</Link>,
    },
  ];

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', padding: '0 24px', background: '#001529' }}>
        <div style={{ color: 'white', fontSize: '20px', fontWeight: 'bold' }}>
          VIP Memory
        </div>
      </Header>
      <AntLayout>
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          width={200}
          theme="light"
        >
          <LazyMenu
            mode="inline"
            selectedKeys={[location.pathname]}
            style={{ height: '100%', borderRight: 0 }}
            items={menuItems}
          />
        </Sider>
        <Content style={{ padding: '24px', minHeight: 280 }}>
          {children}
        </Content>
      </AntLayout>
    </AntLayout>
  );
};

export default Layout;
