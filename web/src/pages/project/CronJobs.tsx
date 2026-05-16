import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import {
  Button,
  Table,
  Switch,
  Tag,
  Space,
  Drawer,
  Popconfirm,
  message,
  Tooltip,
  Typography,
} from 'antd';

import {
  useCronJobs,
  useCronLoading,
  useCronSubmitting,
  useCronActions,
  useCronJobRuns,
} from '@/stores/cron';

import { CronJobForm } from '@/components/cron/CronJobForm';

import type { CronJobResponse, CronJobCreate, CronJobUpdate, CronRunStatus } from '@/types/cron';

export const CronJobs: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const jobs = useCronJobs();
  const runs = useCronJobRuns();
  const loading = useCronLoading();
  const submitting = useCronSubmitting();
  const { fetchJobs, createJob, updateJob, deleteJob, toggleJob, triggerRun, fetchRuns } =
    useCronActions();

  const [formOpen, setFormOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<CronJobResponse | null>(null);

  useEffect(() => {
    if (projectId) {
      void fetchJobs(projectId);
    }
  }, [projectId, fetchJobs]);

  const handleCreateNew = () => {
    setEditingJob(null);
    setFormOpen(true);
  };

  const handleEdit = (job: CronJobResponse) => {
    setEditingJob(job);
    setFormOpen(true);
  };

  const handleViewRuns = (jobId: string) => {
    if (projectId) {
      void fetchRuns(projectId, jobId);
    }
    setRunsOpen(true);
  };

  const handleFormSubmit = async (values: CronJobCreate | CronJobUpdate) => {
    if (!projectId) return;
    try {
      if (editingJob) {
        await updateJob(projectId, editingJob.id, values as CronJobUpdate);
        message.success(t('project.cronJobs.updateSuccess'));
      } else {
        await createJob(projectId, values as CronJobCreate);
        message.success(t('project.cronJobs.createSuccess'));
      }
      setFormOpen(false);
    } catch (_err) {
      message.error(t('project.cronJobs.saveFailed'));
    }
  };

  const handleToggle = async (jobId: string, enabled: boolean) => {
    if (!projectId) return;
    try {
      await toggleJob(projectId, jobId, enabled);
      message.success(
        enabled
          ? t('project.cronJobs.toggleSuccessEnabled')
          : t('project.cronJobs.toggleSuccessDisabled')
      );
    } catch (_err) {
      message.error(t('project.cronJobs.toggleFailed'));
    }
  };

  const handleRunNow = async (jobId: string) => {
    if (!projectId) return;
    try {
      await triggerRun(projectId, jobId);
      message.success(t('project.cronJobs.triggerSuccess'));
      // Refresh runs if drawer is open
      if (runsOpen) {
        void fetchRuns(projectId, jobId);
      }
    } catch (_err) {
      message.error(t('project.cronJobs.triggerFailed'));
    }
  };

  const handleDelete = async (jobId: string) => {
    if (!projectId) return;
    try {
      await deleteJob(projectId, jobId);
      message.success(t('project.cronJobs.deleteSuccess'));
    } catch (_err) {
      message.error(t('project.cronJobs.deleteFailed'));
    }
  };

  const getStatusColor = (status?: CronRunStatus) => {
    switch (status) {
      case 'success':
        return 'success';
      case 'failed':
        return 'error';
      case 'timeout':
        return 'warning';
      case 'skipped':
        return 'default';
      default:
        return 'default';
    }
  };

  const columns = [
    {
      title: t('project.cronJobs.columnsName'),
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: CronJobResponse) => (
        <Tooltip title={record.description}>
          <span className="block max-w-[220px] truncate font-medium">{text}</span>
        </Tooltip>
      ),
      width: 240,
    },
    {
      title: t('project.cronJobs.columnsSchedule'),
      key: 'schedule',
      render: (_: unknown, record: CronJobResponse) => {
        const { kind, config } = record.schedule;
        const scheduleConfig = config as { expression?: string; target_time?: string };
        if (kind === 'cron')
          return (
            <Tag color="blue">
              {t('project.cronJobs.scheduleCron')}: {scheduleConfig.expression ?? '-'}
            </Tag>
          );
        if (kind === 'every')
          return <Tag color="purple">{t('project.cronJobs.scheduleEvery')}</Tag>;
        return (
          <Tag color="cyan">
            {t('project.cronJobs.scheduleAt')}: {scheduleConfig.target_time ?? '-'}
          </Tag>
        );
      },
      width: 160,
    },
    {
      title: t('project.cronJobs.columnsPayload'),
      key: 'payload',
      render: (_: unknown, record: CronJobResponse) => {
        return <Tag>{record.payload.kind}</Tag>;
      },
      width: 140,
    },
    {
      title: t('project.cronJobs.columnsEnabled'),
      dataIndex: 'enabled',
      key: 'enabled',
      render: (enabled: boolean, record: CronJobResponse) => (
        <Switch
          checked={enabled}
          loading={submitting}
          aria-label={t('project.cronJobs.toggleJob', { name: record.name })}
          onChange={(checked) => {
            void handleToggle(record.id, checked);
          }}
        />
      ),
      width: 110,
    },
    {
      title: t('project.cronJobs.columnsActions'),
      key: 'actions',
      render: (_: unknown, record: CronJobResponse) => (
        <Space size="middle">
          <Button
            type="link"
            onClick={() => {
              handleEdit(record);
            }}
            className="p-0"
          >
            {t('project.cronJobs.edit')}
          </Button>
          <Button
            type="link"
            onClick={() => {
              handleViewRuns(record.id);
            }}
            className="p-0"
          >
            {t('project.cronJobs.history')}
          </Button>
          <Button
            type="link"
            onClick={() => {
              void handleRunNow(record.id);
            }}
            className="p-0"
          >
            {t('project.cronJobs.runNow')}
          </Button>
          <Popconfirm
            title={t('project.cronJobs.deleteConfirm')}
            onConfirm={() => {
              void handleDelete(record.id);
            }}
          >
            <Button type="link" danger className="p-0">
              {t('common.delete')}
            </Button>
          </Popconfirm>
        </Space>
      ),
      width: 250,
    },
  ];

  const runColumns = [
    {
      title: t('project.cronJobs.runStatus'),
      dataIndex: 'status',
      key: 'status',
      render: (status: CronRunStatus) => <Tag color={getStatusColor(status)}>{status}</Tag>,
    },
    {
      title: t('project.cronJobs.runTrigger'),
      dataIndex: 'trigger_type',
      key: 'trigger_type',
    },
    {
      title: t('project.cronJobs.runStartedAt'),
      dataIndex: 'started_at',
      key: 'started_at',
      render: (val: string) => new Date(val).toLocaleString(),
    },
    {
      title: t('project.cronJobs.runDurationMs'),
      dataIndex: 'duration_ms',
      key: 'duration_ms',
    },
    {
      title: t('project.cronJobs.runError'),
      dataIndex: 'error_message',
      key: 'error_message',
      render: (val: string | null) => (val ? <span className="text-red-500">{val}</span> : '-'),
    },
  ];

  const jobsPagination = jobs.length > 20 ? { pageSize: 20, showSizeChanger: false } : false;
  const runsPagination = runs.length > 10 ? { pageSize: 10, showSizeChanger: false } : false;

  return (
    <div className="p-4 sm:p-6">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Typography.Title level={2} className="!mb-1">
            {t('project.cronJobs.title')}
          </Typography.Title>
          <Typography.Text type="secondary">{t('project.cronJobs.description')}</Typography.Text>
        </div>
        <Button type="primary" onClick={handleCreateNew}>
          {t('project.cronJobs.createJob')}
        </Button>
      </div>

      <div className="min-w-0 overflow-hidden">
        <Table
          dataSource={jobs}
          columns={columns}
          rowKey="id"
          loading={loading && !submitting}
          pagination={jobsPagination}
          scroll={{ x: 900 }}
        />
      </div>

      <CronJobForm
        open={formOpen}
        onClose={() => {
          setFormOpen(false);
        }}
        onSubmit={handleFormSubmit}
        initialData={editingJob}
        isSubmitting={submitting}
      />

      <Drawer
        title={t('project.cronJobs.runHistoryTitle')}
        size="large"
        onClose={() => {
          setRunsOpen(false);
        }}
        open={runsOpen}
      >
        <Table
          dataSource={runs}
          columns={runColumns}
          rowKey="id"
          loading={loading}
          pagination={runsPagination}
          scroll={{ x: 760 }}
        />
      </Drawer>
    </div>
  );
};
