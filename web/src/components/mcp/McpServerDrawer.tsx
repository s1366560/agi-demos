/**
 * McpServerDrawer - Side drawer for creating and editing MCP servers.
 * Replaces McpServerModal with an Ant Design Drawer for more form space.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Drawer, Form, Input, Select, Switch, message, Alert, Button } from 'antd';
import { useShallow } from 'zustand/react/shallow';

import { useMCPStore } from '@/stores/mcp';
import { useProjectStore } from '@/stores/project';

import type { MCPServerResponse, MCPServerCreate, MCPServerType } from '@/types/agent';

const { TextArea } = Input;

const DEFAULT_TRANSPORT_CONFIGS: Record<MCPServerType, object> = {
  stdio: { command: '', args: [], env: {} },
  sse: { url: '', headers: {} },
  http: { url: '', headers: {} },
  websocket: { url: '' },
};

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
  const [form] = Form.useForm();
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
  const prevServerIdRef = useRef<string | undefined>(server?.id);

  const { createServer, updateServer, isSubmitting } = useMCPStore(
    useShallow((s) => ({
      createServer: s.createServer,
      updateServer: s.updateServer,
      isSubmitting: s.isSubmitting,
    }))
  );
  const { projects, currentProject } = useProjectStore(
    useShallow((s) => ({ projects: s.projects, currentProject: s.currentProject }))
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
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
        project_id: server.project_id,
      });
      setJsonConfig(JSON.stringify(server.transport_config, null, 2));
      setJsonError(null);
    } else {
      form.resetFields();
      form.setFieldsValue({
        server_type: 'stdio',
        enabled: true,
        project_id: currentProject?.id,
      });
      setJsonConfig(JSON.stringify(DEFAULT_TRANSPORT_CONFIGS.stdio, null, 2));
      setJsonError(null);
    }
  }, [server, form, currentProject]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleServerTypeChange = useCallback((type: MCPServerType) => {
    setJsonConfig(JSON.stringify(DEFAULT_TRANSPORT_CONFIGS[type], null, 2));
    setJsonError(null);
  }, []);

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

  const handleSubmit = useCallback(async () => {
    try {
      await form.validateFields(['project_id', 'name', 'server_type']);
      const values = form.getFieldsValue();

      if (!validateJsonConfig(jsonConfig)) {
        message.error('Invalid JSON configuration');
        return;
      }

      const transportConfig = JSON.parse(jsonConfig);
      const projectId = values.project_id;
      if (!projectId) {
        message.error('Please select a project');
        return;
      }

      const data: MCPServerCreate = {
        name: values.name,
        description: values.description,
        server_type: values.server_type,
        transport_config: transportConfig,
        enabled: values.enabled ?? true,
        project_id: projectId,
      };

      if (isEdit && server) {
        await updateServer(server.id, data);
        message.success('Server updated successfully');
      } else {
        await createServer(data);
        message.success('Server created successfully');
      }
      onSuccess();
    } catch (error: unknown) {
      const err = error as { errorFields?: unknown };
      if (!err.errorFields) {
        console.error('Submit error:', error);
      }
    }
  }, [form, jsonConfig, validateJsonConfig, isEdit, server, updateServer, createServer, onSuccess]);

  return (
    <Drawer
      title={isEdit ? 'Edit MCP Server' : 'Create MCP Server'}
      open={open}
      onClose={onClose}
      width={520}
      destroyOnClose
      extra={
        <Button type="primary" onClick={handleSubmit} loading={isSubmitting}>
          {isEdit ? 'Save' : 'Create'}
        </Button>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item
          label="Project"
          name="project_id"
          rules={[{ required: true, message: 'Please select a project' }]}
        >
          <Select
            placeholder="Select a project"
            disabled={isEdit}
            options={projects.map((p) => ({ label: p.name, value: p.id }))}
            showSearch
            filterOption={(input, option) =>
              (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Form.Item
          label="Name"
          name="name"
          rules={[
            { required: true, message: 'Name is required' },
            { max: 100, message: 'Name must be less than 100 characters' },
          ]}
        >
          <Input placeholder="My MCP Server" />
        </Form.Item>

        <Form.Item label="Description" name="description">
          <TextArea rows={2} placeholder="Server description (optional)" />
        </Form.Item>

        <Form.Item
          label="Server Type"
          name="server_type"
          rules={[{ required: true, message: 'Server type is required' }]}
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

        <Form.Item label="Enabled" name="enabled" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item label="Transport Config">
          <TextArea
            value={jsonConfig}
            onChange={(e) => {
              setJsonConfig(e.target.value);
              validateJsonConfig(e.target.value);
            }}
            rows={10}
            className="font-mono text-sm"
            status={jsonError ? 'error' : undefined}
          />
          {jsonError && <Alert type="error" message={jsonError} showIcon className="mt-2" />}
        </Form.Item>
      </Form>
    </Drawer>
  );
};
