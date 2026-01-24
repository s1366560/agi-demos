/**
 * Tenant Agent Configuration View Component (T100, T089)
 *
 * Read-only display of tenant-level agent configuration.
 * Accessible to all authenticated users (FR-021).
 *
 * Features:
 * - Display current tenant agent configuration
 * - Shows all config fields with descriptions
 * - Indicates if config is default or custom
 * - Edit button for admin users (opens T101 editor)
 * - Loading and error states
 *
 * Access Control:
 * - All authenticated users can view
 * - Only tenant admins see edit button
 */

import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Spin, Tag, Typography } from 'antd';
import { EditOutlined, ReloadOutlined } from '@ant-design/icons';
import type { TenantAgentConfig } from '@/types/agent';
import { agentConfigService, TenantAgentConfigError } from '@/services/agentConfigService';

const { Title, Text } = Typography;

interface TenantAgentConfigViewProps {
  /**
   * Tenant ID to display configuration for
   */
  tenantId: string;

  /**
   * Whether current user can edit the config
   * If true, shows edit button
   */
  canEdit?: boolean;

  /**
   * Callback when edit button is clicked
   * Opens the TenantAgentConfigEditor modal
   */
  onEdit?: () => void;

  /**
   * Additional CSS class name
   */
  className?: string;
}

/**
 * Format a timestamp as a localized date/time string
 */
function formatTimestamp(isoString: string): string {
  return new Date(isoString).toLocaleString();
}

/**
 * Component for displaying tenant agent configuration
 */
export function TenantAgentConfigView({
  tenantId,
  canEdit = false,
  onEdit,
  className,
}: TenantAgentConfigViewProps) {
  const [config, setConfig] = useState<TenantAgentConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await agentConfigService.getConfig(tenantId);
      setConfig(data);
    } catch (err) {
      if (err instanceof TenantAgentConfigError) {
        setError(err.message);
      } else {
        setError('Failed to load configuration');
      }
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  // Loading state
  if (loading) {
    return (
      <div className={`flex justify-center items-center p-8 ${className || ''}`}>
        <Spin size="large" tip="Loading configuration..." />
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className={className || ''}>
        <Alert
          type="error"
          message="Configuration Error"
          description={error}
          showIcon
          action={
            <Button size="small" onClick={loadConfig}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  // No config state (shouldn't happen as API returns default)
  if (!config) {
    return (
      <div className={className || ''}>
        <Alert
          type="warning"
          message="No Configuration"
          description="Unable to load tenant agent configuration."
          showIcon
          action={
            <Button size="small" icon={<ReloadOutlined />} onClick={loadConfig}>
              Reload
            </Button>
          }
        />
      </div>
    );
  }

  const isDefault = config.config_type === 'default';

  return (
    <div className={className || ''}>
      <Card
        title={
          <div className="flex items-center justify-between">
            <Title level={4} style={{ margin: 0 }}>
              Agent Configuration
            </Title>
            <Tag color={isDefault ? 'default' : 'blue'}>
              {isDefault ? 'Default' : 'Custom'}
            </Tag>
          </div>
        }
        extra={
          canEdit && onEdit ? (
            <Button
              type="primary"
              icon={<EditOutlined />}
              onClick={onEdit}
              aria-label="Edit configuration"
            >
              Edit
            </Button>
          ) : undefined
        }
      >
        {isDefault && (
          <Alert
            type="info"
            message="Using Default Configuration"
            description="This tenant is using the default agent configuration. Contact your tenant administrator to customize settings."
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}

        <Descriptions column={{ xs: 1, sm: 2 }} bordered size="small">
          {/* LLM Settings */}
          <Descriptions.Item label="LLM Model" span={2}>
            <Text code>{config.llm_model}</Text>
          </Descriptions.Item>

          <Descriptions.Item label="Temperature">
            <Text>{config.llm_temperature}</Text>
            <Text type="secondary" style={{ marginLeft: 8 }}>
              (0-2, lower = more focused)
            </Text>
          </Descriptions.Item>

          {/* Agent Features */}
          <Descriptions.Item label="Pattern Learning">
            <Tag color={config.pattern_learning_enabled ? 'green' : 'red'}>
              {config.pattern_learning_enabled ? 'Enabled' : 'Disabled'}
            </Tag>
          </Descriptions.Item>

          <Descriptions.Item label="Multi-Level Thinking">
            <Tag color={config.multi_level_thinking_enabled ? 'green' : 'red'}>
              {config.multi_level_thinking_enabled ? 'Enabled' : 'Disabled'}
            </Tag>
          </Descriptions.Item>

          {/* Limits */}
          <Descriptions.Item label="Max Work Plan Steps">
            <Text>{config.max_work_plan_steps} steps</Text>
          </Descriptions.Item>

          <Descriptions.Item label="Tool Timeout">
            <Text>{config.tool_timeout_seconds}s</Text>
          </Descriptions.Item>

          {/* Tool Configuration */}
          <Descriptions.Item label="Enabled Tools" span={2}>
            {config.enabled_tools.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {config.enabled_tools.map((tool) => (
                  <Tag key={tool} color="green">
                    {tool}
                  </Tag>
                ))}
              </div>
            ) : (
              <Text type="secondary">All tools enabled (no explicit list)</Text>
            )}
          </Descriptions.Item>

          <Descriptions.Item label="Disabled Tools" span={2}>
            {config.disabled_tools.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {config.disabled_tools.map((tool) => (
                  <Tag key={tool} color="red">
                    {tool}
                  </Tag>
                ))}
              </div>
            ) : (
              <Text type="secondary">No tools disabled</Text>
            )}
          </Descriptions.Item>

          {/* Metadata */}
          <Descriptions.Item label="Last Updated" span={2}>
            <Text type="secondary">{formatTimestamp(config.updated_at)}</Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}

export default TenantAgentConfigView;
