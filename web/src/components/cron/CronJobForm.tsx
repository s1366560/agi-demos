import React, { useEffect } from 'react';

import { Form, Input, Switch, Select, InputNumber, Drawer, Button, Space, Divider } from 'antd';

import type {
  CronJobCreate,
  CronJobUpdate,
  CronJobResponse,
  ScheduleConfig,
  ScheduleType,
} from '@/types/cron';

export interface CronJobFormProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (values: CronJobCreate | CronJobUpdate) => Promise<void>;
  initialData?: CronJobResponse | null;
  isSubmitting?: boolean;
}

const toFiniteNumber = (value: unknown): number | undefined => {
  if (value === undefined || value === null || value === '') {
    return undefined;
  }

  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : undefined;
};

const getDefaultScheduleConfig = (kind: ScheduleType): Record<string, unknown> => {
  if (kind === 'every') {
    return { hours: 0, minutes: 5, seconds: 0 };
  }

  if (kind === 'at') {
    return { run_at: '' };
  }

  return { expr: '0 * * * *' };
};

const normalizeScheduleForForm = (schedule: ScheduleConfig): ScheduleConfig => {
  const config = schedule.config;

  if (schedule.kind === 'every') {
    const intervalSeconds = toFiniteNumber(config.interval_seconds);
    if (intervalSeconds === undefined) {
      return schedule;
    }

    return {
      ...schedule,
      config: {
        ...config,
        hours: Math.floor(intervalSeconds / 3600),
        minutes: Math.floor((intervalSeconds % 3600) / 60),
        seconds: intervalSeconds % 60,
      },
    };
  }

  if (schedule.kind === 'cron') {
    return {
      ...schedule,
      config: {
        ...config,
        expr: config.expr ?? config.expression ?? '0 * * * *',
      },
    };
  }

  return {
    ...schedule,
    config: {
      ...config,
      run_at: config.run_at ?? config.target_time ?? '',
    },
  };
};

const normalizeScheduleForSubmit = (
  schedule: ScheduleConfig | null | undefined
): ScheduleConfig | null | undefined => {
  if (!schedule) {
    return schedule;
  }

  const config = schedule.config;

  if (schedule.kind === 'every') {
    const { hours: _hours, minutes: _minutes, seconds: _seconds, ...configWithoutParts } = config;
    const existingIntervalSeconds = toFiniteNumber(config.interval_seconds);
    const hours = toFiniteNumber(config.hours);
    const minutes = toFiniteNumber(config.minutes);
    const seconds = toFiniteNumber(config.seconds);
    const intervalSeconds =
      hours !== undefined || minutes !== undefined || seconds !== undefined
        ? (hours ?? 0) * 3600 + (minutes ?? 0) * 60 + (seconds ?? 0)
        : existingIntervalSeconds;

    return {
      ...schedule,
      config: {
        ...configWithoutParts,
        interval_seconds: intervalSeconds ?? 0,
      },
    };
  }

  if (schedule.kind === 'cron') {
    const { expression: _expression, ...configWithoutExpression } = config;

    return {
      ...schedule,
      config: {
        ...configWithoutExpression,
        expr: config.expr ?? config.expression,
      },
    };
  }

  const { target_time: _targetTime, ...configWithoutTargetTime } = config;

  return {
    ...schedule,
    config: {
      ...configWithoutTargetTime,
      run_at: config.run_at ?? config.target_time,
    },
  };
};

export const CronJobForm: React.FC<CronJobFormProps> = ({
  open,
  onClose,
  onSubmit,
  initialData,
  isSubmitting = false,
}) => {
  const [form] = Form.useForm();
  const scheduleKind = Form.useWatch(['schedule', 'kind'], form) as string | undefined;
  const payloadKind = Form.useWatch(['payload', 'kind'], form) as string | undefined;

  useEffect(() => {
    if (open) {
      if (initialData) {
        form.setFieldsValue({
          name: initialData.name,
          description: initialData.description,
          enabled: initialData.enabled,
          delete_after_run: initialData.delete_after_run,
          schedule: normalizeScheduleForForm(initialData.schedule),
          payload: initialData.payload,
          delivery: initialData.delivery,
          conversation_mode: initialData.conversation_mode,
          stagger_seconds: initialData.stagger_seconds,
          timeout_seconds: initialData.timeout_seconds,
          max_retries: initialData.max_retries,
        });
      } else {
        form.resetFields();
        form.setFieldsValue({
          enabled: true,
          schedule: { kind: 'cron', config: getDefaultScheduleConfig('cron') },
          payload: { kind: 'system_event', config: { content: '' } },
          delivery: { kind: 'none', config: {} },
          conversation_mode: 'reuse',
          stagger_seconds: 0,
          timeout_seconds: 300,
          max_retries: 0,
          delete_after_run: false,
        });
      }
    }
  }, [open, initialData, form]);

  const handleSubmit = () => {
    form
      .validateFields()
      .then((values: CronJobCreate | CronJobUpdate) => {
        const payload = {
          ...values,
          schedule: normalizeScheduleForSubmit(values.schedule),
        } as CronJobCreate | CronJobUpdate;

        void onSubmit(payload).then(() => {
          form.resetFields();
        });
      })
      .catch((_err: unknown) => {
        console.error('Validation failed:', _err);
      });
  };

  return (
    <Drawer
      title={initialData ? 'Edit Scheduled Task' : 'Create Scheduled Task'}
      size="large"
      onClose={onClose}
      open={open}
      extra={
        <Space>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="primary"
            onClick={() => {
              handleSubmit();
            }}
            loading={isSubmitting}
          >
            {initialData ? 'Save Changes' : 'Create Task'}
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" disabled={isSubmitting}>
        <Divider titlePlacement="left" plain>
          Basic Info
        </Divider>
        <Form.Item
          name="name"
          label="Name"
          rules={[{ required: true, message: 'Name is required' }]}
        >
          <Input placeholder="E.g., Daily Summary Report" />
        </Form.Item>
        <Form.Item name="description" label="Description">
          <Input.TextArea rows={2} placeholder="Optional description..." />
        </Form.Item>
        <Form.Item name="enabled" label="Enabled" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Divider titlePlacement="left" plain>
          Schedule Configuration
        </Divider>
        <Form.Item name={['schedule', 'kind']} label="Schedule Type" rules={[{ required: true }]}>
          <Select
            onChange={(kind: ScheduleType) => {
              form.setFieldValue(['schedule', 'config'], getDefaultScheduleConfig(kind));
            }}
            options={[
              { value: 'cron', label: 'Cron Expression' },
              { value: 'every', label: 'Interval (Every X)' },
              { value: 'at', label: 'Specific Time (One-off)' },
            ]}
          />
        </Form.Item>

        {scheduleKind === 'cron' && (
          <Form.Item
            name={['schedule', 'config', 'expr']}
            label="Cron Expression"
            rules={[{ required: true, message: 'Please enter a valid cron expression' }]}
            help="E.g., '0 * * * *' for every hour, '0 0 * * *' for daily at midnight"
          >
            <Input placeholder="* * * * *" />
          </Form.Item>
        )}

        {scheduleKind === 'every' && (
          <Space align="start">
            <Form.Item name={['schedule', 'config', 'hours']} label="Hours">
              <InputNumber min={0} />
            </Form.Item>
            <Form.Item name={['schedule', 'config', 'minutes']} label="Minutes">
              <InputNumber min={0} max={59} />
            </Form.Item>
            <Form.Item name={['schedule', 'config', 'seconds']} label="Seconds">
              <InputNumber min={0} max={59} />
            </Form.Item>
          </Space>
        )}

        {scheduleKind === 'at' && (
          <Form.Item
            name={['schedule', 'config', 'run_at']}
            label="Target Time (ISO-8601)"
            rules={[{ required: true, message: 'Required for one-off tasks' }]}
          >
            <Input placeholder="2026-03-06T12:00:00Z" />
          </Form.Item>
        )}

        <Divider titlePlacement="left" plain>
          Payload Configuration
        </Divider>
        <Form.Item name={['payload', 'kind']} label="Payload Type" rules={[{ required: true }]}>
          <Select
            options={[
              { value: 'system_event', label: 'System Event' },
              { value: 'agent_turn', label: 'Agent Turn (Send Message)' },
            ]}
          />
        </Form.Item>

        {payloadKind === 'system_event' && (
          <Form.Item
            name={['payload', 'config', 'content']}
            label="Event Content"
            rules={[{ required: true, message: 'Content is required' }]}
          >
            <Input.TextArea rows={3} placeholder="Event payload content..." />
          </Form.Item>
        )}

        {payloadKind === 'agent_turn' && (
          <Form.Item
            name={['payload', 'config', 'message']}
            label="Agent Message"
            rules={[{ required: true, message: 'Message is required' }]}
          >
            <Input.TextArea rows={3} placeholder="Message to send to agent..." />
          </Form.Item>
        )}

        <Divider titlePlacement="left" plain>
          Advanced Settings
        </Divider>

        <Form.Item name="conversation_mode" label="Conversation Mode">
          <Select
            options={[
              { value: 'reuse', label: 'Reuse single conversation' },
              { value: 'fresh', label: 'Create new conversation per run' },
            ]}
          />
        </Form.Item>

        <Form.Item name={['delivery', 'kind']} label="Delivery Method">
          <Select
            options={[
              { value: 'none', label: 'None' },
              { value: 'announce', label: 'Announce Channel' },
              { value: 'webhook', label: 'Webhook' },
            ]}
          />
        </Form.Item>

        <Space align="start" size="large">
          <Form.Item name="timeout_seconds" label="Timeout (s)">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="max_retries" label="Max Retries">
            <InputNumber min={0} max={10} />
          </Form.Item>
          <Form.Item name="delete_after_run" label="Delete After Run" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Space>
      </Form>
    </Drawer>
  );
};
