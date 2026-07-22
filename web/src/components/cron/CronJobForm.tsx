import React, { useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { Form, Input, Switch, Select, InputNumber, Drawer, Button, Space, Divider } from 'antd';

import { confirmAction } from '@/utils/confirmAction';

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
  const { t } = useTranslation();
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

        void onSubmit(payload)
          .then(() => {
            form.resetFields();
          })
          .catch(() => {
            // Submission failed — keep the entered values so the user can retry.
          });
      })
      .catch(() => {
        // Validation failures are expected — antd Form shows inline errors.
      });
  };

  const handleClose = () => {
    if (!form.isFieldsTouched()) {
      onClose();
      return;
    }
    void confirmAction({
      title: t('project.cronJobs.discardChanges', 'Discard unsaved changes?'),
      okText: t('common.discard', 'Discard'),
      cancelText: t('common.cancel'),
      danger: true,
    }).then((confirmed) => {
      if (confirmed) {
        onClose();
      }
    });
  };

  return (
    <Drawer
      title={
        initialData ? t('project.cronJobs.formEditTitle') : t('project.cronJobs.formCreateTitle')
      }
      size="large"
      onClose={handleClose}
      open={open}
      extra={
        <Space>
          <Button onClick={handleClose}>{t('common.cancel')}</Button>
          <Button
            type="primary"
            onClick={() => {
              handleSubmit();
            }}
            loading={isSubmitting}
          >
            {initialData
              ? t('project.cronJobs.formSaveChanges')
              : t('project.cronJobs.formCreateTask')}
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" disabled={isSubmitting}>
        <Divider titlePlacement="left" plain>
          {t('project.cronJobs.formBasicInfo')}
        </Divider>
        <Form.Item
          name="name"
          label={t('project.cronJobs.formName')}
          rules={[{ required: true, message: t('project.cronJobs.formNameRequired') }]}
        >
          <Input placeholder={t('project.cronJobs.formNamePlaceholder')} />
        </Form.Item>
        <Form.Item name="description" label={t('project.cronJobs.formDescription')}>
          <Input.TextArea rows={2} placeholder={t('project.cronJobs.formDescriptionPlaceholder')} />
        </Form.Item>
        <Form.Item name="enabled" label={t('project.cronJobs.formEnabled')} valuePropName="checked">
          <Switch />
        </Form.Item>

        <Divider titlePlacement="left" plain>
          {t('project.cronJobs.formScheduleConfiguration')}
        </Divider>
        <Form.Item
          name={['schedule', 'kind']}
          label={t('project.cronJobs.formScheduleType')}
          rules={[{ required: true }]}
        >
          <Select
            onChange={(kind: ScheduleType) => {
              form.setFieldValue(['schedule', 'config'], getDefaultScheduleConfig(kind));
            }}
            options={[
              { value: 'cron', label: t('project.cronJobs.formScheduleCron') },
              { value: 'every', label: t('project.cronJobs.formScheduleEvery') },
              { value: 'at', label: t('project.cronJobs.formScheduleAt') },
            ]}
          />
        </Form.Item>

        {scheduleKind === 'cron' && (
          <Form.Item
            name={['schedule', 'config', 'expr']}
            label={t('project.cronJobs.formCronExpression')}
            rules={[{ required: true, message: t('project.cronJobs.formCronRequired') }]}
            help={t('project.cronJobs.formCronHelp')}
          >
            <Input placeholder="* * * * *" spellCheck={false} />
          </Form.Item>
        )}

        {scheduleKind === 'every' && (
          <Space align="start">
            <Form.Item
              name={['schedule', 'config', 'hours']}
              label={t('project.cronJobs.formHours')}
            >
              <InputNumber min={0} />
            </Form.Item>
            <Form.Item
              name={['schedule', 'config', 'minutes']}
              label={t('project.cronJobs.formMinutes')}
            >
              <InputNumber min={0} max={59} />
            </Form.Item>
            <Form.Item
              name={['schedule', 'config', 'seconds']}
              label={t('project.cronJobs.formSeconds')}
            >
              <InputNumber min={0} max={59} />
            </Form.Item>
          </Space>
        )}

        {scheduleKind === 'at' && (
          <Form.Item
            name={['schedule', 'config', 'run_at']}
            label={t('project.cronJobs.formTargetTime')}
            rules={[
              { required: true, message: t('project.cronJobs.formTargetTimeRequired') },
              {
                validator: (_rule, value: unknown) =>
                  typeof value !== 'string' || !Number.isNaN(Date.parse(value))
                    ? Promise.resolve()
                    : Promise.reject(
                        new Error(
                          t('project.cronJobs.formTargetTimeInvalid', {
                            defaultValue: 'Enter a valid ISO 8601 date-time',
                          })
                        )
                      ),
              },
            ]}
          >
            <Input placeholder="2026-03-06T12:00:00Z" spellCheck={false} />
          </Form.Item>
        )}

        <Divider titlePlacement="left" plain>
          {t('project.cronJobs.formPayloadConfiguration')}
        </Divider>
        <Form.Item
          name={['payload', 'kind']}
          label={t('project.cronJobs.formPayloadType')}
          rules={[{ required: true }]}
        >
          <Select
            options={[
              { value: 'system_event', label: t('project.cronJobs.formSystemEvent') },
              { value: 'agent_turn', label: t('project.cronJobs.formAgentTurn') },
            ]}
          />
        </Form.Item>

        {payloadKind === 'system_event' && (
          <Form.Item
            name={['payload', 'config', 'content']}
            label={t('project.cronJobs.formEventContent')}
            rules={[{ required: true, message: t('project.cronJobs.formContentRequired') }]}
          >
            <Input.TextArea rows={3} placeholder={t('project.cronJobs.formContentPlaceholder')} />
          </Form.Item>
        )}

        {payloadKind === 'agent_turn' && (
          <Form.Item
            name={['payload', 'config', 'message']}
            label={t('project.cronJobs.formAgentMessage')}
            rules={[{ required: true, message: t('project.cronJobs.formMessageRequired') }]}
          >
            <Input.TextArea rows={3} placeholder={t('project.cronJobs.formMessagePlaceholder')} />
          </Form.Item>
        )}

        <Divider titlePlacement="left" plain>
          {t('project.cronJobs.formAdvancedSettings')}
        </Divider>

        <Form.Item name="conversation_mode" label={t('project.cronJobs.formConversationMode')}>
          <Select
            options={[
              { value: 'reuse', label: t('project.cronJobs.formReuseConversation') },
              { value: 'fresh', label: t('project.cronJobs.formFreshConversation') },
            ]}
          />
        </Form.Item>

        <Form.Item name={['delivery', 'kind']} label={t('project.cronJobs.formDeliveryMethod')}>
          <Select
            options={[
              { value: 'none', label: t('project.cronJobs.formDeliveryNone') },
              { value: 'announce', label: t('project.cronJobs.formDeliveryAnnounce') },
              { value: 'webhook', label: t('project.cronJobs.formDeliveryWebhook') },
            ]}
          />
        </Form.Item>

        <Space align="start" size="large">
          <Form.Item name="timeout_seconds" label={t('project.cronJobs.formTimeoutSeconds')}>
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="max_retries" label={t('project.cronJobs.formMaxRetries')}>
            <InputNumber min={0} max={10} />
          </Form.Item>
          <Form.Item
            name="delete_after_run"
            label={t('project.cronJobs.formDeleteAfterRun')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Space>
      </Form>
    </Drawer>
  );
};
