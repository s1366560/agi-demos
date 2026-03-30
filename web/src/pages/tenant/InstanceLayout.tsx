import React, { useEffect, useState, useRef } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, useLocation, Outlet } from 'react-router-dom';

import { Tag, Space, InputNumber } from 'antd';
import {
  ArrowLeft,
  FileText,
  Network,
  Users,
  Dna,
  Settings,
  LayoutDashboard,
} from 'lucide-react';

import { LazyModal, LazySpin, LazyButton, LazyPopconfirm, useLazyMessage } from '@/components/ui/lazyAntd';

import {
  useCurrentInstance,
  useInstanceLoading,
  useInstanceActions,
} from '../../stores/instance';

import { getStatusColor } from './utils/instanceUtils';

export const InstanceLayout: React.FC = () => {
  const { instanceId: id } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const messageApi = useLazyMessage();
  const tabListRef = useRef<HTMLDivElement>(null);

  const [scaleModalVisible, setScaleModalVisible] = useState(false);
  const [newReplicas, setNewReplicas] = useState<number>(1);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  const instance = useCurrentInstance();
  const isLoading = useInstanceLoading();
  const { getInstance, restartInstance, deleteInstance, scaleInstance } = useInstanceActions();

  useEffect(() => {
    if (id) {
      getInstance(id);
    }
  }, [id, getInstance]);

  const handleBack = () => {
    navigate('..');
  };

  const handleRestart = async () => {
    if (!id) return;
    setIsSubmitting(true);
    try {
      await restartInstance(id);
      messageApi?.success(t('tenant.instances.restartSuccess'));
    } catch {
      messageApi?.error(t('tenant.instances.restartError'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!id) return;
    setIsSubmitting(true);
    try {
      await deleteInstance(id);
      messageApi?.success(t('tenant.instances.deleteSuccess'));
      navigate('..');
    } catch {
      messageApi?.error(t('tenant.instances.deleteError'));
      setIsSubmitting(false);
    }
  };

  const handleScale = async () => {
    if (!id) return;
    setIsSubmitting(true);
    try {
      await scaleInstance(id, newReplicas);
      messageApi?.success(t('tenant.instances.scaleSuccess'));
      setScaleModalVisible(false);
    } catch {
      messageApi?.error(t('tenant.instances.scaleError'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const tabs = [
    { key: 'overview', label: t('tenant.instances.tabs.overview'), icon: <LayoutDashboard size={14} />, path: '.' },
    { key: 'files', label: t('tenant.instances.tabs.files'), icon: <FileText size={14} />, path: 'files' },
    { key: 'channels', label: t('tenant.instances.tabs.channels'), icon: <Network size={14} />, path: 'channels' },
    { key: 'members', label: t('tenant.instances.tabs.members'), icon: <Users size={14} />, path: 'members' },
    { key: 'genes', label: t('tenant.instances.tabs.genes'), icon: <Dna size={14} />, path: 'genes' },
    { key: 'settings', label: t('tenant.instances.tabs.settings'), icon: <Settings size={14} />, path: 'settings' },
  ];

  const getActiveTab = () => {
    const path = location.pathname;
    if (path.endsWith('/files')) return 'files';
    if (path.endsWith('/channels')) return 'channels';
    if (path.endsWith('/members')) return 'members';
    if (path.endsWith('/genes')) return 'genes';
    if (path.endsWith('/settings')) return 'settings';
    return 'overview';
  };

  const activeTab = getActiveTab();

  const handleTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    const tabCount = tabs.length;
    let newIndex: number | null = null;
    
    switch (e.key) {
      case 'ArrowRight':
        newIndex = (index + 1) % tabCount;
        break;
      case 'ArrowLeft':
        newIndex = (index - 1 + tabCount) % tabCount;
        break;
      case 'Home':
        newIndex = 0;
        break;
      case 'End':
        newIndex = tabCount - 1;
        break;
      default:
        return;
    }
    
    e.preventDefault();
    const tabElements = tabListRef.current?.querySelectorAll('[role="tab"]');
    if (tabElements?.[newIndex]) {
      (tabElements[newIndex] as HTMLElement).focus();
    }
  };

  if (!instance && isLoading) {
    return (
      <div className="p-8 text-center flex justify-center">
        <LazySpin size="large" />
      </div>
    );
  }

  if (!instance && !isLoading) {
    return (
      <div className="p-8 text-center flex justify-center">
        {t('common.notFound')}
      </div>
    );
  }

  if (!instance) {
    return null;
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <LazyButton
            type="text"
            icon={<ArrowLeft size={16} />}
            onClick={handleBack}
            aria-label={t('common.back', 'Go back')}
          />
          <div>
            <h1 className="text-2xl font-bold text-text-primary dark:text-text-inverse flex items-center gap-3">
              {instance.name}
              <Tag color={getStatusColor(instance.status)} className="m-0">
                {t(`tenant.instances.status.${instance.status}`)}
              </Tag>
            </h1>
            <p className="text-sm text-text-muted mt-1">ID: {instance.id}</p>
          </div>
        </div>
        <Space>
          <LazyButton
            onClick={() => {
              setNewReplicas(instance.replicas);
              setScaleModalVisible(true);
            }}
            disabled={isSubmitting}
          >
            {t('tenant.instances.actions.scale')}
          </LazyButton>
          <LazyPopconfirm
            title={t('tenant.instances.actions.restartConfirm')}
            onConfirm={handleRestart}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ loading: isSubmitting }}
          >
            <LazyButton disabled={isSubmitting}>{t('tenant.instances.actions.restart')}</LazyButton>
          </LazyPopconfirm>
          <LazyPopconfirm
            title={t('tenant.instances.actions.deleteConfirm')}
            onConfirm={handleDelete}
            okText={t('common.yes')}
            cancelText={t('common.no')}
            okButtonProps={{ danger: true, loading: isSubmitting }}
          >
            <LazyButton danger disabled={isSubmitting}>{t('tenant.instances.actions.delete')}</LazyButton>
          </LazyPopconfirm>
        </Space>
      </div>

      <div 
        ref={tabListRef}
        role="tablist" 
        aria-label={t('tenant.instances.tabs.ariaLabel', 'Instance tabs')}
        className="flex items-center gap-1 border-b border-border-light dark:border-border-dark -mb-2"
      >
        {tabs.map((tab, index) => {
          const isActive = activeTab === tab.key;
          return (
            <button type="button"
              key={tab.key}
              role="tab"
              aria-selected={isActive}
              tabIndex={isActive ? 0 : -1}
              aria-controls="instance-tab-panel"
              onKeyDown={(e) => { handleTabKeyDown(e, index); }}
              onClick={() => navigate(tab.path)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px rounded-none h-auto bg-transparent cursor-pointer ${
                isActive
                  ? 'border-info text-info-dark dark:text-info-light'
                  : 'border-transparent text-text-muted hover:text-text-secondary dark:text-text-muted dark:hover:text-text-inverse hover:border-border-separator'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}
      </div>

      <div id="instance-tab-panel" role="tabpanel" aria-labelledby={`instance-tab-${activeTab}`}>
        <Outlet />
      </div>

      <LazyModal
        title={t('tenant.instances.actions.scale')}
        open={scaleModalVisible}
        onOk={handleScale}
        onCancel={() => {
          if (!isSubmitting) setScaleModalVisible(false);
        }}
        confirmLoading={isSubmitting}
        cancelButtonProps={{ disabled: isSubmitting }}
      >
        <div className="flex items-center gap-4 py-4">
          <span>{t('tenant.instances.detail.replicas')}:</span>
          <InputNumber
            min={0}
            max={10}
            value={newReplicas}
            onChange={(val) => {
              setNewReplicas(val || 0);
            }}
          />
        </div>
      </LazyModal>
    </div>
  );
};
