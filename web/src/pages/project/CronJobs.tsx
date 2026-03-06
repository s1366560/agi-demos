import React, { useEffect, useState } from 'react';

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
        message.success('Scheduled task updated successfully');
      } else {
        await createJob(projectId, values as CronJobCreate);
        message.success('Scheduled task created successfully');
      }
      setFormOpen(false);
    } catch (_err) {
      message.error('Failed to save task');
    }
  };

  const handleToggle = async (jobId: string, enabled: boolean) => {
    if (!projectId) return;
    try {
      await toggleJob(projectId, jobId, enabled);
      message.success(`Task ${enabled ? 'enabled' : 'disabled'}`);
    } catch (_err) {
      message.error('Failed to toggle task');
    }
  };

  const handleRunNow = async (jobId: string) => {
    if (!projectId) return;
    try {
      await triggerRun(projectId, jobId);
      message.success('Task execution triggered');
      // Refresh runs if drawer is open
      if (runsOpen) {
        void fetchRuns(projectId, jobId);
      }
    } catch (_err) {
      message.error('Failed to trigger task');
    }
  };

  const handleDelete = async (jobId: string) => {
    if (!projectId) return;
    try {
      await deleteJob(projectId, jobId);
      message.success('Task deleted');
    } catch (_err) {
      message.error('Failed to delete task');
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
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: CronJobResponse) => (
        <Tooltip title={record.description}>
          <span className="font-medium">{text}</span>
        </Tooltip>
      ),
    },
    {
      title: 'Schedule',
      key: 'schedule',
      render: (_: unknown, record: CronJobResponse) => {
        const { kind, config } = record.schedule;
        const scheduleConfig = config as { expression?: string; target_time?: string };
        if (kind === 'cron')
          return <Tag color="blue">Cron: {scheduleConfig.expression ?? '-'}</Tag>;
        if (kind === 'every') return <Tag color="purple">Every</Tag>;
        return <Tag color="cyan">At: {scheduleConfig.target_time ?? '-'}</Tag>;
      },
    },
    {
      title: 'Payload',
      key: 'payload',
      render: (_: unknown, record: CronJobResponse) => {
        return <Tag>{record.payload.kind}</Tag>;
      },
    },
    {
      title: 'Enabled',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (enabled: boolean, record: CronJobResponse) => (
        <Switch
          checked={enabled}
          loading={submitting}
          onChange={(checked) => { void handleToggle(record.id, checked); }}
        />
      ),
    },
    {
      title: 'Actions',
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
            Edit
          </Button>
          <Button
            type="link"
            onClick={() => {
              handleViewRuns(record.id);
            }}
            className="p-0"
          >
            History
          </Button>
          <Button type="link" onClick={() => { void handleRunNow(record.id); }} className="p-0">
            Run Now
          </Button>
          <Popconfirm title="Delete this task?" onConfirm={() => { void handleDelete(record.id); }}>
            <Button type="link" danger className="p-0">
              Delete
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const runColumns = [
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (status: CronRunStatus) => <Tag color={getStatusColor(status)}>{status}</Tag>,
    },
    {
      title: 'Trigger',
      dataIndex: 'trigger_type',
      key: 'trigger_type',
    },
    {
      title: 'Started At',
      dataIndex: 'started_at',
      key: 'started_at',
      render: (val: string) => new Date(val).toLocaleString(),
    },
    {
      title: 'Duration (ms)',
      dataIndex: 'duration_ms',
      key: 'duration_ms',
    },
    {
      title: 'Error',
      dataIndex: 'error_message',
      key: 'error_message',
      render: (val: string | null) => (val ? <span className="text-red-500">{val}</span> : '-'),
    },
  ];

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <Typography.Title level={2} className="!mb-1">
            Scheduled Tasks
          </Typography.Title>
          <Typography.Text type="secondary">
            Manage automated, recurring, and scheduled background jobs
          </Typography.Text>
        </div>
        <Button type="primary" onClick={handleCreateNew}>
          Create Job
        </Button>
      </div>

      <Table
        dataSource={jobs}
        columns={columns}
        rowKey="id"
        loading={loading && !submitting}
        pagination={{ pageSize: 20 }}
      />

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
        title="Run History"
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
          pagination={{ pageSize: 10 }}
        />
      </Drawer>
    </div>
  );
};
