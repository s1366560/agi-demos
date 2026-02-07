/**
 * MCP Server Modal
 *
 * Modal component for creating and editing MCP servers with JSON-based
 * transport configuration.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Modal, Form, Input, Select, Switch, message, Alert } from 'antd';

import { useMCPStore } from '../../stores/mcp';
import { useProjectStore } from '../../stores/project';

import type { MCPServerResponse, MCPServerCreate, MCPServerType } from '../../types/agent';

const { TextArea } = Input;

interface McpServerModalProps {
  isOpen: boolean;
  server: MCPServerResponse | null;
  onClose: () => void;
  onSuccess: () => void;
}

// Default transport configs by type
const DEFAULT_TRANSPORT_CONFIGS: Record<MCPServerType, object> = {
  stdio: { command: '', args: [], env: {} },
  sse: { url: '', headers: {} },
  http: { url: '', headers: {} },
  websocket: { url: '' },
};

export const McpServerModal: React.FC<McpServerModalProps> = ({
  isOpen,
  server,
  onClose,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();

  // Compute initial JSON config based on server prop
  const initialJsonConfig = useMemo(
    () =>
      server
        ? JSON.stringify(server.transport_config, null, 2)
        : JSON.stringify(DEFAULT_TRANSPORT_CONFIGS.stdio, null, 2),
    [server]
  );

  const [jsonConfig, setJsonConfig] = useState(initialJsonConfig);
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Track server ID to detect changes
  const prevServerIdRef = useRef<string | undefined>(server?.id);

  const { createServer, updateServer, isSubmitting } = useMCPStore();
  const currentProject = useProjectStore((state) => state.currentProject);

  const isEdit = !!server;

  // Initialize form when server changes
  // Note: setState in effect is necessary here for form modal initialization pattern
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    // Check if server actually changed
    if (prevServerIdRef.current === server?.id && prevServerIdRef.current !== undefined) {
      return;
    }
    prevServerIdRef.current = server?.id;

    if (server) {
      form.setFieldsValue({
        name: server.name,
        description: server.description,
        server_type: server.server_type,
        enabled: server.enabled,
      });
      setJsonConfig(JSON.stringify(server.transport_config, null, 2));
      setJsonError(null);
    } else {
      form.resetFields();
      form.setFieldsValue({
        server_type: 'stdio',
        enabled: true,
      });
      setJsonConfig(JSON.stringify(DEFAULT_TRANSPORT_CONFIGS.stdio, null, 2));
      setJsonError(null);
    }
  }, [server, form]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Handle server type change
  const handleServerTypeChange = useCallback((type: MCPServerType) => {
    setJsonConfig(JSON.stringify(DEFAULT_TRANSPORT_CONFIGS[type], null, 2));
    setJsonError(null);
  }, []);

  // Validate JSON config
  const validateJsonConfig = useCallback((json: string): boolean => {
    try {
      JSON.parse(json);
      setJsonError(null);
      return true;
    } catch (e) {
      setJsonError((e as Error).message);
      return false;
    }
  }, []);

  // Build transport config from JSON
  const buildTransportConfig = useCallback((): Record<string, unknown> | null => {
    if (!validateJsonConfig(jsonConfig)) {
      return null;
    }
    return JSON.parse(jsonConfig);
  }, [jsonConfig, validateJsonConfig]);

  // Handle submit
  const handleSubmit = useCallback(async () => {
    try {
      await form.validateFields(['name', 'server_type']);

      const values = form.getFieldsValue();
      const transportConfig = buildTransportConfig();

      if (!transportConfig) {
        message.error(t('tenant.mcpServers.invalidConfig'));
        return;
      }

      const data: MCPServerCreate = {
        name: values.name,
        description: values.description,
        server_type: values.server_type,
        transport_config: transportConfig,
        enabled: values.enabled ?? true,
        project_id: server?.project_id || currentProject?.id || '',
      };

      if (isEdit && server) {
        await updateServer(server.id, data);
        message.success(t('tenant.mcpServers.updateSuccess'));
      } else {
        await createServer(data);
        message.success(t('tenant.mcpServers.createSuccess'));
      }

      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown };
      if (!err.errorFields) {
        // Not a form validation error
        console.error('Submit error:', error);
      }
    }
  }, [form, buildTransportConfig, isEdit, server, updateServer, createServer, onSuccess, t]);

  return (
    <Modal
      title={isEdit ? t('tenant.mcpServers.editTitle') : t('tenant.mcpServers.createTitle')}
      open={isOpen}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={isSubmitting}
      okText={isEdit ? t('common.save') : t('common.create')}
      cancelText={t('common.cancel')}
      width={600}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" className="mt-4">
        {/* Name */}
        <Form.Item
          label={t('tenant.mcpServers.fields.name')}
          name="name"
          rules={[
            {
              required: true,
              message: t('tenant.mcpServers.validation.nameRequired'),
            },
            {
              max: 100,
              message: t('tenant.mcpServers.validation.nameTooLong'),
            },
          ]}
        >
          <Input placeholder={t('tenant.mcpServers.placeholders.name')} />
        </Form.Item>

        {/* Description */}
        <Form.Item label={t('tenant.mcpServers.fields.description')} name="description">
          <TextArea rows={2} placeholder={t('tenant.mcpServers.placeholders.description')} />
        </Form.Item>

        {/* Server Type */}
        <Form.Item
          label={t('tenant.mcpServers.fields.serverType')}
          name="server_type"
          rules={[
            {
              required: true,
              message: t('tenant.mcpServers.validation.typeRequired'),
            },
          ]}
        >
          <Select
            options={[
              { label: 'STDIO (Standard I/O)', value: 'stdio' },
              { label: 'SSE (Server-Sent Events)', value: 'sse' },
              { label: 'HTTP', value: 'http' },
              { label: 'WebSocket', value: 'websocket' },
            ]}
            onChange={handleServerTypeChange}
          />
        </Form.Item>

        {/* Enabled */}
        <Form.Item
          label={t('tenant.mcpServers.fields.enabled')}
          name="enabled"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

        {/* JSON Config */}
        <Form.Item label={t('tenant.mcpServers.fields.transportConfig')}>
          <TextArea
            value={jsonConfig}
            onChange={(e) => {
              setJsonConfig(e.target.value);
              validateJsonConfig(e.target.value);
            }}
            rows={8}
            className="font-mono text-sm"
            status={jsonError ? 'error' : undefined}
          />
          {jsonError && <Alert type="error" message={jsonError} showIcon className="mt-2" />}
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default McpServerModal;
