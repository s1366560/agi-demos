/**
 * McpServerDrawer - Side drawer for creating and editing MCP servers.
 * Replaces McpServerModal with an Ant Design Drawer for more form space.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Drawer, Form, Input, Select, Switch, message, Alert, Button } from 'antd';
import { useShallow } from 'zustand/react/shallow';

import { useMCPStore } from '@/stores/mcp';

import { useMcpProjectScope } from './useMcpProjectScope';

import type { MCPServerResponse, MCPServerCreate, MCPServerType } from '@/types/agent';

const { TextArea } = Input;

const DEFAULT_TRANSPORT_CONFIGS: Record<MCPServerType, Record<string, unknown>> = {
  stdio: { command: '', args: [], env: {} },
  sse: { url: '', headers: {} },
  http: { url: '', headers: {} },
  websocket: { url: '' },
};

interface McpServerFormValues {
  project_id?: string | undefined;
  name?: string | undefined;
  description?: string | undefined;
  server_type?: MCPServerType | undefined;
  enabled?: boolean | undefined;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const hasValidationErrors = (error: unknown): boolean =>
  isRecord(error) && Array.isArray(error.errorFields);

export interface McpServerDrawerProps {
  open: boolean;
  server: MCPServerResponse | null;
  onClose: () => void;
  onSuccess: () => void;
}

export const McpServerDrawer: React.FC<McpServerDrawerProps> = ({
  open,
  server,
  onClose,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm<McpServerFormValues>();
  const isEdit = !!server;

  const initialJsonConfig = useMemo(
    () =>
      server
        ? JSON.stringify(server.transport_config, null, 2)
        : JSON.stringify(DEFAULT_TRANSPORT_CONFIGS.stdio, null, 2),
    [server]
  );

  const [jsonConfig, setJsonConfig] = useState(initialJsonConfig);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const { createServer, updateServer, isSubmitting } = useMCPStore(
    useShallow((s) => ({
      createServer: s.createServer,
      updateServer: s.updateServer,
      isSubmitting: s.isSubmitting,
    }))
  );
  const { projects, projectId } = useMcpProjectScope();

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) {
      return;
    }

    if (server) {
      form.setFieldsValue({
        name: server.name,
        description: server.description,
        server_type: server.server_type,
        enabled: server.enabled,
        project_id: server.project_id,
      });
      setJsonConfig(JSON.stringify(server.transport_config, null, 2));
      setJsonError(null);
    } else {
      form.setFieldsValue({
        server_type: 'stdio',
        enabled: true,
        project_id: projectId,
      });
      setJsonConfig(JSON.stringify(DEFAULT_TRANSPORT_CONFIGS.stdio, null, 2));
      setJsonError(null);
    }
  }, [open, server, form, projectId]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleServerTypeChange = useCallback((type: MCPServerType) => {
    setJsonConfig(JSON.stringify(DEFAULT_TRANSPORT_CONFIGS[type], null, 2));
    setJsonError(null);
  }, []);

  const parseTransportConfig = useCallback(
    (json: string): Record<string, unknown> | null => {
      try {
        const parsed = JSON.parse(json) as unknown;
        if (!isRecord(parsed)) {
          setJsonError(t('mcp.serverDrawer.jsonObjectRequired'));
          return null;
        }
        setJsonError(null);
        return parsed;
      } catch (e) {
        setJsonError(e instanceof Error ? e.message : t('mcp.serverDrawer.invalidJson'));
        return null;
      }
    },
    [t]
  );

  const handleSubmit = useCallback(async () => {
    try {
      await form.validateFields(['project_id', 'name', 'server_type']);
      const values = form.getFieldsValue();

      const transportConfig = parseTransportConfig(jsonConfig);
      if (!transportConfig) {
        message.error(t('mcp.serverDrawer.invalidJson'));
        return;
      }

      const projectId = values.project_id;
      if (!projectId) {
        message.error(t('mcp.serverDrawer.projectRequired'));
        return;
      }
      const name = values.name;
      const serverType = values.server_type;
      if (!name || !serverType) {
        message.error(t('mcp.serverDrawer.requiredFields'));
        return;
      }

      const data: MCPServerCreate = {
        name,
        description: values.description,
        server_type: serverType,
        transport_config: transportConfig,
        enabled: values.enabled ?? true,
        project_id: projectId,
      };

      if (server) {
        await updateServer(server.id, data);
        message.success(t('mcp.serverDrawer.updateSuccess'));
      } else {
        await createServer(data);
        message.success(t('mcp.serverDrawer.createSuccess'));
      }
      onSuccess();
    } catch (error: unknown) {
      if (!hasValidationErrors(error)) {
        console.error('Submit error:', error);
      }
    }
  }, [form, jsonConfig, parseTransportConfig, server, updateServer, createServer, onSuccess, t]);

  return (
    <Drawer
      title={isEdit ? t('mcp.serverDrawer.editTitle') : t('mcp.serverDrawer.createTitle')}
      open={open}
      onClose={onClose}
      size="large"
      destroyOnHidden
      extra={
        <Button
          type="primary"
          onClick={() => {
            void handleSubmit();
          }}
          loading={isSubmitting}
        >
          {isEdit ? t('common.save') : t('common.create')}
        </Button>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item
          label={t('common.project')}
          name="project_id"
          rules={[{ required: true, message: t('mcp.serverDrawer.projectRequired') }]}
        >
          <Select
            placeholder={t('mcp.serverDrawer.projectPlaceholder')}
            disabled={isEdit}
            options={projects.map((p) => ({ label: p.name, value: p.id }))}
            showSearch={{
              filterOption: (input, option) =>
                typeof option?.label === 'string' &&
                option.label.toLowerCase().includes(input.toLowerCase()),
            }}
          />
        </Form.Item>

        <Form.Item
          label={t('common.forms.name')}
          name="name"
          rules={[
            { required: true, message: t('mcp.serverDrawer.nameRequired') },
            { max: 100, message: t('mcp.serverDrawer.nameMax') },
          ]}
        >
          <Input placeholder={t('mcp.serverDrawer.namePlaceholder')} />
        </Form.Item>

        <Form.Item label={t('common.forms.description')} name="description">
          <TextArea rows={2} placeholder={t('mcp.serverDrawer.descriptionPlaceholder')} />
        </Form.Item>

        <Form.Item
          label={t('mcp.serverDrawer.serverType')}
          name="server_type"
          rules={[{ required: true, message: t('mcp.serverDrawer.serverTypeRequired') }]}
        >
          <Select
            options={[
              { label: t('mcp.serverDrawer.serverTypes.stdio'), value: 'stdio' },
              { label: t('mcp.serverDrawer.serverTypes.sse'), value: 'sse' },
              { label: t('mcp.serverDrawer.serverTypes.http'), value: 'http' },
              { label: t('mcp.serverDrawer.serverTypes.websocket'), value: 'websocket' },
            ]}
            onChange={handleServerTypeChange}
          />
        </Form.Item>

        <Form.Item label={t('common.status.enabled')} name="enabled" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item label={t('mcp.serverDrawer.transportConfig')}>
          <TextArea
            value={jsonConfig}
            onChange={(e) => {
              setJsonConfig(e.target.value);
              parseTransportConfig(e.target.value);
            }}
            rows={10}
            className="font-mono text-sm"
            status={jsonError ? 'error' : ('' as const)}
          />
          {jsonError && <Alert type="error" title={jsonError} showIcon className="mt-2" />}
        </Form.Item>
      </Form>
    </Drawer>
  );
};
