import React, { useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import { Timeline, Button, Badge, Card, Typography, Spin, Alert, Collapse, Space } from 'antd';

import { useAuthStore } from '../../stores/auth';
import {
  useDeploys,
  useCurrentDeploy,
  useDeployLoading,
  useDeployError,
  useDeployActions,
} from '../../stores/deploy';

const { Title, Text, Paragraph } = Typography;

const getStatusColor = (status: string) => {
  switch (status) {
    case 'pending':
      return 'blue';
    case 'in_progress':
      return 'orange';
    case 'success':
      return 'green';
    case 'failed':
      return 'red';
    case 'cancelled':
      return 'gray';
    default:
      return 'default';
  }
};

export const DeployProgress: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId, deployId } = useParams();
  const navigate = useNavigate();

  const deploys = useDeploys();
  const currentDeploy = useCurrentDeploy();
  const loading = useDeployLoading();
  const error = useDeployError();
  const { listDeploys, getDeploy, createDeploy, markSuccess, markFailed, cancelDeploy } =
    useDeployActions();

  useEffect(() => {
    if (deployId) {
      getDeploy(deployId).catch(() => {});
    } else if (instanceId) {
      listDeploys({ instance_id: instanceId }).catch(() => {});
    }
  }, [instanceId, deployId, getDeploy, listDeploys]);

  useEffect(() => {
    if (
      !deployId ||
      !currentDeploy ||
      ['success', 'failed', 'cancelled'].includes(currentDeploy.status)
    ) {
      return;
    }

    const token = useAuthStore.getState().token;
    if (!token) return;

    const es = new EventSource(`/api/v1/deploys/${deployId}/progress?token=${token}`);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as { type: string };
        if (data.type === 'status') {
          getDeploy(deployId).catch(() => {});
        }
        if (data.type === 'done') {
          getDeploy(deployId).catch(() => {});
          es.close();
        }
      } catch {
        /* empty */
      }
    };

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, [deployId, currentDeploy, getDeploy]);

  const handleNewDeploy = () => {
    if (!instanceId) return;
    createDeploy({ instance_id: instanceId, description: 'Manual deploy' })
      .then((res) => {
        navigate(`../deploy/${res.id}`);
      })
      .catch(() => {});
  };

  if (loading && !deploys.length && !currentDeploy) {
    return (
      <div className="flex justify-center p-12">
        <Spin size="large" />
      </div>
    );
  }

  if (deployId) {
    if (!currentDeploy)
      return <Alert type="warning" message={t('tenant.deploy.notFound', 'Deploy not found')} />;

    const timelineItems = [
      {
        color: 'gray',
        children: (
          <>
            <Text strong>{t('tenant.deploy.states.created', 'Created')}</Text>
            <br />
            <Text type="secondary">{new Date(currentDeploy.created_at).toLocaleString()}</Text>
          </>
        ),
      },
      {
        color: currentDeploy.started_at ? 'blue' : 'gray',
        children: (
          <>
            <Text strong>{t('tenant.deploy.states.inProgress', 'In Progress')}</Text>
            {currentDeploy.started_at && (
              <>
                <br />
                <Text type="secondary">{new Date(currentDeploy.started_at).toLocaleString()}</Text>
              </>
            )}
          </>
        ),
      },
      {
        color: ['success', 'failed', 'cancelled'].includes(currentDeploy.status)
          ? getStatusColor(currentDeploy.status)
          : 'gray',
        children: (
          <>
            <Text strong>
              {currentDeploy.status === 'success'
                ? t('tenant.deploy.states.success', 'Success')
                : currentDeploy.status === 'failed'
                  ? t('tenant.deploy.states.failed', 'Failed')
                  : currentDeploy.status === 'cancelled'
                    ? t('tenant.deploy.states.cancelled', 'Cancelled')
                    : t('tenant.deploy.states.completed', 'Completed')}
            </Text>
            {currentDeploy.completed_at && (
              <>
                <br />
                <Text type="secondary">
                  {new Date(currentDeploy.completed_at).toLocaleString()}
                </Text>
              </>
            )}
            {currentDeploy.error_message && (
              <Alert type="error" message={currentDeploy.error_message} className="mt-2" />
            )}
          </>
        ),
      },
    ];

    return (
      <div className="max-w-4xl mx-auto w-full flex flex-col gap-8">
        <div className="flex items-center gap-4">
          <Button onClick={() => navigate(-1)}>{t('tenant.deploy.actions.back', 'Back')}</Button>
          <Title level={3} className="!mb-0">
            {t('tenant.deploy.detailTitle', 'Deployment Detail')}
          </Title>
          <Badge
            color={getStatusColor(currentDeploy.status)}
            text={currentDeploy.status.toUpperCase()}
            className="ml-auto scale-125"
          />
        </div>

        {error && <Alert type="error" message={error} />}

        <Card className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="grid grid-cols-2 gap-8 mb-8">
            <div>
              <Text type="secondary">{t('tenant.deploy.fields.id', 'ID')}</Text>
              <Paragraph copyable>{currentDeploy.id}</Paragraph>

              <Text type="secondary">{t('tenant.deploy.fields.image', 'Image Version')}</Text>
              <Paragraph>{currentDeploy.image_version || '-'}</Paragraph>

              <Text type="secondary">{t('tenant.deploy.fields.triggeredBy', 'Triggered By')}</Text>
              <Paragraph>{currentDeploy.triggered_by || '-'}</Paragraph>
            </div>
            <div>
              <Timeline items={timelineItems} />
            </div>
          </div>

          <Collapse
            items={[
              {
                key: 'config',
                label: t('tenant.deploy.fields.config', 'Configuration Snapshot'),
                children: (
                  <pre className="bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto text-xs">
                    {JSON.stringify(currentDeploy.config_snapshot, null, 2)}
                  </pre>
                ),
              },
            ]}
          />

          <div className="mt-8 pt-4 border-t border-slate-200 dark:border-slate-700 flex gap-4">
            {currentDeploy.status === 'in_progress' && (
              <Button danger onClick={() => cancelDeploy(currentDeploy.id).catch(() => {})}>
                {t('tenant.deploy.actions.cancel', 'Cancel Deploy')}
              </Button>
            )}
            <Space className="ml-auto">
              {currentDeploy.status !== 'success' && (
                <Button onClick={() => markSuccess(currentDeploy.id).catch(() => {})}>
                  {t('tenant.deploy.actions.markSuccess', 'Mark Success')}
                </Button>
              )}
              {currentDeploy.status !== 'failed' && (
                <Button danger onClick={() => markFailed(currentDeploy.id).catch(() => {})}>
                  {t('tenant.deploy.actions.markFailed', 'Mark Failed')}
                </Button>
              )}
            </Space>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-8">
      <div className="flex items-center justify-between">
        <Title level={3} className="!mb-0">
          {t('tenant.deploy.listTitle', 'Deployment History')}
        </Title>
        <Button type="primary" onClick={handleNewDeploy}>
          {t('tenant.deploy.actions.new', 'New Deploy')}
        </Button>
      </div>

      {error && <Alert type="error" message={error} />}

      <Card className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
        <Timeline
          items={deploys.map((d) => ({
            color: getStatusColor(d.status),
            children: (
              <button
                type="button"
                className="w-full text-left cursor-pointer bg-transparent border-none hover:bg-slate-50 dark:hover:bg-slate-800 p-2 rounded -ml-2 transition-colors"
                onClick={() => navigate(`../deploy/${d.id}`)}
              >
                <div className="flex justify-between items-start mb-1">
                  <Text strong>
                    {d.description || t('tenant.deploy.defaultDescription', 'System Update')}
                  </Text>
                  <Text type="secondary" className="text-xs">
                    {new Date(d.created_at).toLocaleString()}
                  </Text>
                </div>
                <div className="flex gap-4 text-sm">
                  <Badge color={getStatusColor(d.status)} text={d.status} />
                  <Text type="secondary">{d.image_version}</Text>
                  {d.triggered_by && <Text type="secondary">by {d.triggered_by}</Text>}
                </div>
              </button>
            ),
          }))}
        />
        {deploys.length === 0 && !loading && (
          <div className="text-center text-slate-500 py-8">
            {t('tenant.deploy.empty', 'No deployments found')}
          </div>
        )}
      </Card>
    </div>
  );
};
