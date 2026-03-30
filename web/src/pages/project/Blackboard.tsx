import type React from 'react';
import { useEffect, useState, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { Empty, Typography, Select, Spin, Alert } from 'antd';

import { useBlackboardError, useBlackboardActions } from '@/stores/blackboard';

import { workspaceService } from '@/services/workspaceService';

import { PostDetail } from '@/components/blackboard/PostDetail';
import { PostList } from '@/components/blackboard/PostList';

import type { Workspace } from '@/types/workspace';

const { Title } = Typography;

export const Blackboard: React.FC = () => {
  const { tenantId, projectId } = useParams<{ tenantId: string; projectId: string }>();
  const { t } = useTranslation();

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [workspacesLoading, setWorkspacesLoading] = useState(true);
  const [workspacesError, setWorkspacesError] = useState<string | null>(null);

  const error = useBlackboardError();
  const { fetchPosts, reset } = useBlackboardActions();

  useEffect(() => {
    return () => {
      reset();
    };
  }, [reset]);

  const loadWorkspaces = useCallback(async () => {
    if (!tenantId || !projectId) return;

    setWorkspacesLoading(true);
    setWorkspacesError(null);
    try {
      const result = await workspaceService.listByProject(tenantId, projectId);
      setWorkspaces(result);
      if (result.length > 0 && result[0]) {
        setSelectedWorkspaceId(result[0].id);
      }
    } catch (err: unknown) {
      setWorkspacesError(err instanceof Error ? err.message : String(err));
    } finally {
      setWorkspacesLoading(false);
    }
  }, [tenantId, projectId]);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    if (tenantId && projectId && selectedWorkspaceId) {
      void fetchPosts(tenantId, projectId, selectedWorkspaceId);
    }
  }, [tenantId, projectId, selectedWorkspaceId, fetchPosts]);

  if (workspacesLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spin size="large" />
      </div>
    );
  }

  if (workspacesError) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <Alert 
          type="error" 
          message={t('common.error', 'Error')} 
          description={workspacesError} 
          showIcon 
        />
      </div>
    );
  }

  if (workspaces.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 bg-gray-50/30">
        <Empty 
          description={t('blackboard.noWorkspaces', 'No workspaces found')} 
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-6 flex items-center justify-between">
        <Title level={4} className="!mb-0">
          {t('blackboard.title')}
        </Title>
        <Select
          value={selectedWorkspaceId}
          onChange={setSelectedWorkspaceId}
          className="w-64"
          options={workspaces.map((ws) => ({ label: ws.name, value: ws.id }))}
          disabled={workspacesLoading}
        />
      </div>

      {error && (
        <Alert 
          type="error" 
          message={error} 
          showIcon 
          closable 
          className="mb-4 shadow-sm" 
        />
      )}

      {selectedWorkspaceId && tenantId && projectId && (
        <div className="flex min-h-0 flex-1 flex-col gap-6 md:flex-row">
          <div className="flex w-full flex-col md:w-[40%]">
            <PostList
              tenantId={tenantId}
              projectId={projectId}
              workspaceId={selectedWorkspaceId}
            />
          </div>
          <div className="flex w-full flex-col md:w-[60%]">
            <PostDetail
              tenantId={tenantId}
              projectId={projectId}
              workspaceId={selectedWorkspaceId}
            />
          </div>
        </div>
      )}
    </div>
  );
};
