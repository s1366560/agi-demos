import React, { useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';

import { Timeline, Badge, Card, Typography, Alert, Collapse, Space } from 'antd';

import {
  LazyButton,
  LazySpin,
  LazyEmpty,
  LazyPopconfirm,
  useLazyMessage,
} from '@/components/ui/lazyAntd';

import { useAuthStore } from '../../stores/auth';
import {
  useDeploys,
  useCurrentDeploy,
  useDeployLoading,
  useDeployError,
  useDeployActions,
} from '../../stores/deploy';

import { streamDeployProgress } from './deployProgressStream';
import { getStatusColor, formatDate } from './utils/instanceUtils';

const { Title, Text, Paragraph } = Typography;

export const DeployProgress: React.FC = () => {
  const { t } = useTranslation();
  const { instanceId, deployId } = useParams();
  const navigate = useNavigate();
  const messageApi = useLazyMessage();

  const deploysFromStore = useDeploys();
  const deploys = Array.isArray(deploysFromStore) ? deploysFromStore : [];
  const currentDeploy = useCurrentDeploy();
  const loading = useDeployLoading();
  const error = useDeployError();
  const { listDeploys, getDeploy, createDeploy, markSuccess, markFailed, cancelDeploy } =
    useDeployActions();

  useEffect(() => {
    if (deployId) {
      getDeploy(deployId).catch((err: unknown) => {
        console.error('Failed to get deploy:', err);
        messageApi?.error(t('tenant.deploy.errors.getFailed', 'Failed to fetch deploy details'));
      });
    } else if (instanceId) {
      listDeploys({ instance_id: instanceId }).catch((err: unknown) => {
        console.error('Failed to list deploys:', err);
        messageApi?.error(t('tenant.deploy.errors.listFailed', 'Failed to fetch deploy history'));
      });
    }
  }, [instanceId, deployId, getDeploy, listDeploys, messageApi, t]);

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

    const controller = new AbortController();

    const refreshDeploy = (context: string): void => {
      getDeploy(deployId).catch((err: unknown) => {
        console.error(`Failed to get deploy ${context}:`, err);
      });
    };

    void streamDeployProgress({
      deployId,
      token,
      signal: controller.signal,
      onEvent: (data) => {
        if (data.type === 'status') {
          refreshDeploy('status update');
        }
        if (data.type === 'done') {
          refreshDeploy('final status');
        }
      },
    }).catch((err: unknown) => {
      if (controller.signal.aborted) {
        return;
      }
      try {
        console.error('Deploy progress stream error:', err);
      } catch {
        // Ignore logger failures.
      }
    });

    return () => {
      controller.abort();
    };
  }, [deployId, currentDeploy, getDeploy]);

  const handleNewDeploy = () => {
    if (!instanceId) return;
    void createDeploy({ instance_id: instanceId, description: 'Manual deploy' })
      .then((res) => {
        void navigate(`../deploy/${res.id}`);
      })
      .catch((err: unknown) => {
        console.error('Failed to create deploy:', err);
        messageApi?.error(t('tenant.deploy.errors.createFailed', 'Failed to create new deploy'));
      });
  };

  if (loading && !deploys.length && !currentDeploy) {
    return (
      <div className="flex justify-center p-12">
        <LazySpin size="large" />
      </div>
    );
  }

  if (deployId) {
    if (!currentDeploy)
      return <Alert type="warning" title={t('tenant.deploy.notFound', 'Deploy not found')} />;

    const timelineItems = [
      {
        color: 'gray',
        children: (
          <>
            <Text strong>{t('tenant.deploy.states.created', 'Created')}</Text>
            <br />
            <Text type="secondary">{formatDate(currentDeploy.created_at)}</Text>
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
                <Text type="secondary">{formatDate(currentDeploy.started_at)}</Text>
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
                <Text type="secondary">{formatDate(currentDeploy.completed_at)}</Text>
              </>
            )}
            {currentDeploy.error_message && (
              <Alert type="error" title={currentDeploy.error_message} className="mt-2" />
            )}
          </>
        ),
      },
    ];

    return (
      <div className="max-w-4xl mx-auto w-full flex flex-col gap-8">
        <div className="flex items-center gap-4">
          <LazyButton
            onClick={() => {
              void navigate(-1);
            }}
          >
            {t('tenant.deploy.actions.back', 'Back')}
          </LazyButton>
          <Title level={3} className="!mb-0">
            {t('tenant.deploy.detailTitle', 'Deployment Detail')}
          </Title>
          <Badge
            color={getStatusColor(currentDeploy.status)}
            text={currentDeploy.status.toUpperCase()}
            className="ml-auto scale-125"
          />
        </div>

        {error && <Alert type="error" title={error} />}

        <Card className="bg-surface-light dark:bg-surface-dark rounded-lg p-6 border border-border-light dark:border-border-dark">
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
                  <pre className="bg-surface-alt dark:bg-surface-dark-alt p-4 rounded overflow-auto text-xs">
                    {JSON.stringify(currentDeploy.config_snapshot, null, 2)}
                  </pre>
                ),
              },
            ]}
          />

          <div className="mt-8 pt-4 border-t border-border-light dark:border-border-dark flex gap-4">
            {currentDeploy.status === 'in_progress' && (
              <LazyPopconfirm
                title={t(
                  'tenant.deploy.actions.cancelConfirm',
                  'Are you sure you want to cancel this deploy?'
                )}
                okText={t('common.actions.yes', 'Yes')}
                cancelText={t('common.actions.no', 'No')}
                onConfirm={() => {
                  void cancelDeploy(currentDeploy.id).catch((err: unknown) => {
                    console.error('Failed to cancel deploy:', err);
                    messageApi?.error(
                      t('tenant.deploy.errors.cancelFailed', 'Failed to cancel deploy')
                    );
                  });
                }}
              >
                <LazyButton danger>{t('tenant.deploy.actions.cancel', 'Cancel Deploy')}</LazyButton>
              </LazyPopconfirm>
            )}
            <Space className="ml-auto">
              {currentDeploy.status !== 'success' && (
                <LazyPopconfirm
                  title={t(
                    'tenant.deploy.actions.markSuccessConfirm',
                    'Are you sure you want to mark this deploy as success?'
                  )}
                  okText={t('common.actions.yes', 'Yes')}
                  cancelText={t('common.actions.no', 'No')}
                  onConfirm={() => {
                    void markSuccess(currentDeploy.id).catch((err: unknown) => {
                      console.error('Failed to mark deploy as success:', err);
                      messageApi?.error(
                        t(
                          'tenant.deploy.errors.markSuccessFailed',
                          'Failed to update deploy status'
                        )
                      );
                    });
                  }}
                >
                  <LazyButton>{t('tenant.deploy.actions.markSuccess', 'Mark Success')}</LazyButton>
                </LazyPopconfirm>
              )}
              {currentDeploy.status !== 'failed' && (
                <LazyPopconfirm
                  title={t(
                    'tenant.deploy.actions.markFailedConfirm',
                    'Are you sure you want to mark this deploy as failed?'
                  )}
                  okText={t('common.actions.yes', 'Yes')}
                  cancelText={t('common.actions.no', 'No')}
                  onConfirm={() => {
                    void markFailed(currentDeploy.id).catch((err: unknown) => {
                      console.error('Failed to mark deploy as failed:', err);
                      messageApi?.error(
                        t('tenant.deploy.errors.markFailedFailed', 'Failed to update deploy status')
                      );
                    });
                  }}
                >
                  <LazyButton danger>
                    {t('tenant.deploy.actions.markFailed', 'Mark Failed')}
                  </LazyButton>
                </LazyPopconfirm>
              )}
            </Space>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <Title level={3} className="!mb-0">
          {t('tenant.deploy.listTitle', 'Deployment History')}
        </Title>
        <LazyButton type="primary" onClick={handleNewDeploy}>
          {t('tenant.deploy.actions.new', 'New Deploy')}
        </LazyButton>
      </div>

      {error && <Alert type="error" title={error} />}

      <Card className="bg-surface-light dark:bg-surface-dark rounded-lg p-6 border border-border-light dark:border-border-dark">
        <Timeline
          items={deploys.map((d) => ({
            color: getStatusColor(d.status),
            children: (
              <Card
                size="small"
                hoverable
                className="w-full cursor-pointer -ml-2"
                onClick={() => {
                  void navigate(`../deploy/${d.id}`);
                }}
              >
                <div className="flex justify-between items-start mb-1">
                  <Text strong>
                    {d.description || t('tenant.deploy.defaultDescription', 'System Update')}
                  </Text>
                  <Text type="secondary" className="text-xs">
                    {formatDate(d.created_at)}
                  </Text>
                </div>
                <div className="flex gap-4 text-sm">
                  <Badge color={getStatusColor(d.status)} text={d.status} />
                  <Text type="secondary">{d.image_version}</Text>
                  {d.triggered_by && <Text type="secondary">by {d.triggered_by}</Text>}
                </div>
              </Card>
            ),
          }))}
        />
        {deploys.length === 0 && !loading && (
          <div className="text-center text-text-muted py-8">
            <LazyEmpty description={t('tenant.deploy.empty', 'No deployments found')} />
          </div>
        )}
      </Card>
    </div>
  );
};
