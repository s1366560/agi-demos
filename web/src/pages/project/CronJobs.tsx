import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import {
  Alert,
  Button,
  Input,
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

import { RefreshCw } from 'lucide-react';

import {
  useCronJobs,
  useCronLoading,
  useCronSubmitting,
  useCronActions,
  useCronJobRuns,
  useCronTotal,
  useCronRunsTotal,
  useCronFilters,
} from '@/stores/cron';

import { formatDateTime } from '@/utils/date';

import { CronJobForm } from '@/components/cron/CronJobForm';

import type {
  CronJobResponse,
  CronJobCreate,
  CronJobUpdate,
  CronRunStatus,
  CronJobRunResponse,
  TriggerType,
} from '@/types/cron';

import type { TableProps } from 'antd/es/table';

const RUNS_PAGE_SIZE = 10;

const formatDurationMs = (ms: number): string =>
  ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${String(ms)} ms`;

export const CronJobs: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const jobs = useCronJobs();
  const runs = useCronJobRuns();
  const total = useCronTotal();
  const runsTotal = useCronRunsTotal();
  const filters = useCronFilters();
  const loading = useCronLoading();
  const submitting = useCronSubmitting();
  const {
    fetchJobs,
    createJob,
    updateJob,
    deleteJob,
    toggleJob,
    triggerRun,
    fetchRuns,
    setFilters,
  } = useCronActions();

  const [formOpen, setFormOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<CronJobResponse | null>(null);
  const [runsJobId, setRunsJobId] = useState<string | null>(null);
  const [runsPage, setRunsPage] = useState(1);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [nameSearch, setNameSearch] = useState('');

  // Client-side name filter for the currently loaded page of jobs.
  const visibleJobs = useMemo(() => {
    const needle = nameSearch.trim().toLowerCase();
    if (!needle) return jobs;
    return jobs.filter((job) => job.name.toLowerCase().includes(needle));
  }, [jobs, nameSearch]);

  // The cron store rethrows on failure; catch here so rejections are handled
  // and the page can show an error state with a retry action.
  const loadJobs = useCallback(async () => {
    if (!projectId) return;
    try {
      await fetchJobs(projectId);
      setJobsError(null);
    } catch {
      setJobsError(t('project.cronJobs.loadFailed', 'Failed to load cron jobs.'));
    }
  }, [projectId, fetchJobs, t]);

  const loadRuns = useCallback(
    async (jobId: string, page: number) => {
      if (!projectId) return;
      try {
        await fetchRuns(projectId, jobId, RUNS_PAGE_SIZE, (page - 1) * RUNS_PAGE_SIZE);
      } catch {
        message.error(t('project.cronJobs.runsLoadFailed', 'Failed to load run history.'));
      }
    },
    [projectId, fetchRuns, t]
  );

  useEffect(() => {
    // Inline loader: the retry button and pagination use loadJobs instead.
    const loadInitialJobs = async () => {
      if (!projectId) return;
      try {
        await fetchJobs(projectId);
        setJobsError(null);
      } catch {
        setJobsError(t('project.cronJobs.loadFailed', 'Failed to load cron jobs.'));
      }
    };
    void loadInitialJobs();
  }, [projectId, fetchJobs, t]);

  const handleCreateNew = () => {
    setEditingJob(null);
    setFormOpen(true);
  };

  const handleEdit = (job: CronJobResponse) => {
    setEditingJob(job);
    setFormOpen(true);
  };

  const handleViewRuns = (jobId: string) => {
    setRunsJobId(jobId);
    setRunsPage(1);
    void loadRuns(jobId, 1);
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
      // Rethrow so CronJobForm keeps the entered values instead of resetting.
      throw _err;
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
      if (runsOpen && runsJobId === jobId) {
        void loadRuns(jobId, runsPage);
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

  const handleJobsTableChange: TableProps<CronJobResponse>['onChange'] = (pagination) => {
    const nextPage = pagination.current ?? filters.page;
    const nextPageSize = pagination.pageSize ?? filters.pageSize;

    setFilters({ page: nextPage, pageSize: nextPageSize });
    void loadJobs();
  };

  const handleRunsTableChange: TableProps<CronJobRunResponse>['onChange'] = (pagination) => {
    const nextPage = pagination.current ?? runsPage;

    setRunsPage(nextPage);
    if (runsJobId) {
      void loadRuns(runsJobId, nextPage);
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
            title={t('project.cronJobs.deleteConfirmNamed', {
              defaultValue: 'Delete job "{{name}}"?',
              name: record.name,
            })}
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
      render: (status: CronRunStatus) => (
        <Tag color={getStatusColor(status)}>
          {t(`project.cronJobs.runStatusValue.${status}`, status)}
        </Tag>
      ),
    },
    {
      title: t('project.cronJobs.runTrigger'),
      dataIndex: 'trigger_type',
      key: 'trigger_type',
      render: (triggerType: TriggerType) =>
        t(`project.cronJobs.triggerType.${triggerType}`, triggerType),
    },
    {
      title: t('project.cronJobs.runStartedAt'),
      dataIndex: 'started_at',
      key: 'started_at',
      render: (val: string) => formatDateTime(val),
    },
    {
      title: t('project.cronJobs.runDurationMs'),
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      render: (val: number | null) =>
        val === null ? '-' : <span className="tabular-nums">{formatDurationMs(val)}</span>,
    },
    {
      title: t('project.cronJobs.runError'),
      dataIndex: 'error_message',
      key: 'error_message',
      render: (val: string | null) => (val ? <span className="text-red-500">{val}</span> : '-'),
    },
  ];

  const jobsPagination =
    total > filters.pageSize
      ? {
          current: filters.page,
          pageSize: filters.pageSize,
          total,
          showSizeChanger: false,
          showTotal: (paginationTotal: number, range: [number, number]) =>
            t('project.cronJobs.paginationTotal', {
              start: range[0],
              end: range[1],
              total: paginationTotal,
            }),
        }
      : false;
  const runsPagination =
    runsTotal > RUNS_PAGE_SIZE
      ? {
          current: runsPage,
          pageSize: RUNS_PAGE_SIZE,
          total: runsTotal,
          showSizeChanger: false,
          showTotal: (paginationTotal: number, range: [number, number]) =>
            t('project.cronJobs.runPaginationTotal', {
              start: range[0],
              end: range[1],
              total: paginationTotal,
            }),
        }
      : false;

  return (
    <div className="p-4 sm:p-6">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Typography.Title level={2} className="!mb-1">
            {t('project.cronJobs.title')}
          </Typography.Title>
          <Typography.Text type="secondary">{t('project.cronJobs.description')}</Typography.Text>
        </div>
        <Space wrap>
          <Input
            allowClear
            value={nameSearch}
            onChange={(event) => {
              setNameSearch(event.target.value);
            }}
            placeholder={t('project.cronJobs.searchPlaceholder', 'Search by name')}
            aria-label={t('project.cronJobs.searchPlaceholder', 'Search by name')}
            className="w-56"
          />
          <Button
            icon={<RefreshCw size={14} aria-hidden="true" />}
            onClick={() => {
              void loadJobs();
            }}
            loading={loading && !submitting}
          >
            {t('common.refresh', 'Refresh')}
          </Button>
          <Button type="primary" onClick={handleCreateNew}>
            {t('project.cronJobs.createJob')}
          </Button>
        </Space>
      </div>

      <div className="min-w-0 overflow-hidden">
        {jobsError && (
          <Alert
            type="error"
            showIcon
            className="mb-4"
            title={jobsError}
            action={
              <Button
                size="small"
                onClick={() => {
                  void loadJobs();
                }}
              >
                {t('common.retry', 'Retry')}
              </Button>
            }
          />
        )}
        <Table
          dataSource={visibleJobs}
          columns={columns}
          rowKey="id"
          loading={loading && !submitting}
          pagination={jobsPagination}
          onChange={handleJobsTableChange}
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
        afterOpenChange={(open) => {
          if (!open) {
            setRunsJobId(null);
            setRunsPage(1);
          }
        }}
      >
        <Table
          dataSource={runs}
          columns={runColumns}
          rowKey="id"
          loading={loading}
          pagination={runsPagination}
          onChange={handleRunsTableChange}
          scroll={{ x: 760 }}
        />
      </Drawer>
    </div>
  );
};
