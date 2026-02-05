/**
 * Agent Pool Dashboard - 池化管理仪表板
 *
 * 显示Agent Pool的状态、实例列表和指标数据。
 *
 * @packageDocumentation
 */

import React, { useEffect, useCallback, useRef } from "react";

import {
  ReloadOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  StopOutlined,
  ThunderboltOutlined,
  CloudOutlined,
  HistoryOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import {
  Card,
  Row,
  Col,
  Statistic,
  Table,
  Tag,
  Space,
  Button,
  Select,
  Tooltip,
  Progress,
  Switch,
  Typography,
  Alert,
  Popconfirm,
  message,
} from "antd";


import { usePoolStore } from "../../stores/pool";

import type { PoolInstance, ProjectTier } from "../../services/poolService";
import type { ColumnsType } from "antd/es/table";

const { Title, Text } = Typography;

// ============================================================================
// Helper Components
// ============================================================================

const TierTag: React.FC<{ tier: ProjectTier }> = ({ tier }) => {
  const config = {
    hot: { color: "red", icon: <ThunderboltOutlined />, label: "HOT" },
    warm: { color: "orange", icon: <CloudOutlined />, label: "WARM" },
    cold: { color: "blue", icon: <HistoryOutlined />, label: "COLD" },
  };

  const { color, icon, label } = config[tier] || config.cold;

  return (
    <Tag color={color} icon={icon}>
      {label}
    </Tag>
  );
};

const StatusTag: React.FC<{ status: string }> = ({ status }) => {
  const config: Record<string, { color: string; icon: React.ReactNode }> = {
    ready: { color: "green", icon: <CheckCircleOutlined /> },
    executing: { color: "blue", icon: <ThunderboltOutlined /> },
    paused: { color: "orange", icon: <PauseCircleOutlined /> },
    unhealthy: { color: "red", icon: <ExclamationCircleOutlined /> },
    degraded: { color: "gold", icon: <ExclamationCircleOutlined /> },
    initializing: { color: "cyan", icon: <ReloadOutlined spin /> },
    terminated: { color: "default", icon: <StopOutlined /> },
    initialization_failed: { color: "red", icon: <CloseCircleOutlined /> },
  };

  const { color, icon } = config[status] || { color: "default", icon: null };

  return (
    <Tag color={color} icon={icon}>
      {status.toUpperCase()}
    </Tag>
  );
};

const HealthTag: React.FC<{ health: string }> = ({ health }) => {
  const config: Record<string, { color: string }> = {
    healthy: { color: "green" },
    degraded: { color: "gold" },
    unhealthy: { color: "red" },
    unknown: { color: "default" },
  };

  const { color } = config[health] || { color: "default" };

  return <Tag color={color}>{health.toUpperCase()}</Tag>;
};

// ============================================================================
// Main Component
// ============================================================================

const PoolDashboard: React.FC = () => {
  const {
    // Status
    status,
    isStatusLoading,
    statusError,
    fetchStatus,
    // Instances
    instances,
    totalInstances,
    currentPage,
    pageSize,
    isInstancesLoading,
    instancesError,
    fetchInstances,
    setPage,
    setTierFilter,
    tierFilter,
    // Operations
    pauseInstance,
    resumeInstance,
    terminateInstance,
    // Metrics
    fetchMetrics,
    // Auto-refresh
    autoRefresh,
    setAutoRefresh,
    refreshInterval,
  } = usePoolStore();

  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Initial load
  useEffect(() => {
    fetchStatus();
    fetchInstances();
    fetchMetrics();
  }, [fetchStatus, fetchInstances, fetchMetrics]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh) {
      refreshTimerRef.current = setInterval(() => {
        fetchStatus();
        fetchInstances();
        fetchMetrics();
      }, refreshInterval * 1000);
    }

    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [autoRefresh, refreshInterval, fetchStatus, fetchInstances, fetchMetrics]);

  const handleRefresh = useCallback(() => {
    fetchStatus();
    fetchInstances();
    fetchMetrics();
  }, [fetchStatus, fetchInstances, fetchMetrics]);

  const handlePause = async (instanceKey: string) => {
    const success = await pauseInstance(instanceKey);
    if (success) {
      message.success("Instance paused");
    } else {
      message.error("Failed to pause instance");
    }
  };

  const handleResume = async (instanceKey: string) => {
    const success = await resumeInstance(instanceKey);
    if (success) {
      message.success("Instance resumed");
    } else {
      message.error("Failed to resume instance");
    }
  };

  const handleTerminate = async (instanceKey: string) => {
    const success = await terminateInstance(instanceKey);
    if (success) {
      message.success("Instance terminated");
    } else {
      message.error("Failed to terminate instance");
    }
  };

  // Table columns
  const columns: ColumnsType<PoolInstance> = [
    {
      title: "Instance Key",
      dataIndex: "instance_key",
      key: "instance_key",
      width: 250,
      ellipsis: true,
      render: (key: string) => (
        <Tooltip title={key}>
          <Text code style={{ fontSize: 12 }}>
            {key}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: "Tier",
      dataIndex: "tier",
      key: "tier",
      width: 100,
      render: (tier: ProjectTier) => <TierTag tier={tier} />,
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      width: 140,
      render: (status: string) => <StatusTag status={status} />,
    },
    {
      title: "Health",
      dataIndex: "health_status",
      key: "health_status",
      width: 100,
      render: (health: string) => <HealthTag health={health} />,
    },
    {
      title: "Requests",
      key: "requests",
      width: 120,
      render: (_: unknown, record: PoolInstance) => (
        <Space direction="vertical" size={0}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Active: {record.active_requests}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Total: {record.total_requests}
          </Text>
        </Space>
      ),
    },
    {
      title: "Memory",
      dataIndex: "memory_used_mb",
      key: "memory_used_mb",
      width: 100,
      render: (mb: number) => `${mb.toFixed(1)} MB`,
    },
    {
      title: "Last Request",
      dataIndex: "last_request_at",
      key: "last_request_at",
      width: 160,
      render: (time: string | null) =>
        time ? new Date(time).toLocaleString() : "-",
    },
    {
      title: "Actions",
      key: "actions",
      width: 150,
      fixed: "right",
      render: (_: unknown, record: PoolInstance) => (
        <Space size="small">
          {record.status === "ready" || record.status === "executing" ? (
            <Tooltip title="Pause">
              <Button
                type="text"
                size="small"
                icon={<PauseCircleOutlined />}
                onClick={() => handlePause(record.instance_key)}
              />
            </Tooltip>
          ) : record.status === "paused" ? (
            <Tooltip title="Resume">
              <Button
                type="text"
                size="small"
                icon={<PlayCircleOutlined />}
                onClick={() => handleResume(record.instance_key)}
              />
            </Tooltip>
          ) : null}
          <Popconfirm
            title="Terminate this instance?"
            onConfirm={() => handleTerminate(record.instance_key)}
            okText="Yes"
            cancelText="No"
          >
            <Tooltip title="Terminate">
              <Button
                type="text"
                size="small"
                danger
                icon={<StopOutlined />}
              />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // Calculate resource usage percentages
  const memoryUsagePct = status?.resource_usage
    ? (status.resource_usage.used_memory_mb /
        status.resource_usage.total_memory_mb) *
      100
    : 0;
  const cpuUsagePct = status?.resource_usage
    ? (status.resource_usage.used_cpu_cores /
        status.resource_usage.total_cpu_cores) *
      100
    : 0;

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <div
        style={{
          marginBottom: 24,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <Title level={2} style={{ margin: 0 }}>
          Agent Pool Dashboard
        </Title>
        <Space>
          <Text type="secondary">Auto-refresh</Text>
          <Switch
            checked={autoRefresh}
            onChange={setAutoRefresh}
            size="small"
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={handleRefresh}
            loading={isStatusLoading || isInstancesLoading}
          >
            Refresh
          </Button>
        </Space>
      </div>

      {/* Error alerts */}
      {statusError && (
        <Alert
          message="Failed to load pool status"
          description={statusError}
          type="error"
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Status Overview */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title="Total Instances"
              value={status?.total_instances ?? 0}
              prefix={<CloudOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title="Ready"
              value={status?.ready_instances ?? 0}
              valueStyle={{ color: "#52c41a" }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title="Executing"
              value={status?.executing_instances ?? 0}
              valueStyle={{ color: "#1890ff" }}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={isStatusLoading}>
            <Statistic
              title="Unhealthy"
              value={status?.unhealthy_instances ?? 0}
              valueStyle={{
                color: (status?.unhealthy_instances ?? 0) > 0 ? "#f5222d" : undefined,
              }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* Tier Distribution & Resources */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={12}>
          <Card title="Tier Distribution" loading={isStatusLoading}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title={
                    <Space>
                      <ThunderboltOutlined style={{ color: "#f5222d" }} />
                      HOT
                    </Space>
                  }
                  value={status?.hot_instances ?? 0}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title={
                    <Space>
                      <CloudOutlined style={{ color: "#fa8c16" }} />
                      WARM
                    </Space>
                  }
                  value={status?.warm_instances ?? 0}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title={
                    <Space>
                      <HistoryOutlined style={{ color: "#1890ff" }} />
                      COLD
                    </Space>
                  }
                  value={status?.cold_instances ?? 0}
                />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Resource Usage" loading={isStatusLoading}>
            <Space direction="vertical" style={{ width: "100%" }}>
              <div>
                <Text type="secondary">Memory</Text>
                <Progress
                  percent={Math.round(memoryUsagePct)}
                  status={memoryUsagePct > 80 ? "exception" : "normal"}
                  format={() =>
                    `${status?.resource_usage?.used_memory_mb?.toFixed(0) ?? 0} / ${status?.resource_usage?.total_memory_mb?.toFixed(0) ?? 0} MB`
                  }
                />
              </div>
              <div>
                <Text type="secondary">CPU</Text>
                <Progress
                  percent={Math.round(cpuUsagePct)}
                  status={cpuUsagePct > 80 ? "exception" : "normal"}
                  format={() =>
                    `${status?.resource_usage?.used_cpu_cores?.toFixed(1) ?? 0} / ${status?.resource_usage?.total_cpu_cores?.toFixed(1) ?? 0} cores`
                  }
                />
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* Prewarm Pool */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={24}>
          <Card title="Prewarm Pool" loading={isStatusLoading}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="L1 (Hot)"
                  value={status?.prewarm_pool?.l1 ?? 0}
                  suffix="instances"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="L2 (Warm)"
                  value={status?.prewarm_pool?.l2 ?? 0}
                  suffix="instances"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="L3 (Cold)"
                  value={status?.prewarm_pool?.l3 ?? 0}
                  suffix="instances"
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* Instances Table */}
      <Card
        title="Active Instances"
        extra={
          <Space>
            <Select
              placeholder="Filter by tier"
              allowClear
              style={{ width: 120 }}
              value={tierFilter}
              onChange={setTierFilter}
              options={[
                { value: "hot", label: "HOT" },
                { value: "warm", label: "WARM" },
                { value: "cold", label: "COLD" },
              ]}
            />
          </Space>
        }
      >
        {instancesError && (
          <Alert
            message={instancesError}
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}
        <Table
          columns={columns}
          dataSource={instances}
          rowKey="instance_key"
          loading={isInstancesLoading}
          pagination={{
            current: currentPage,
            pageSize: pageSize,
            total: totalInstances,
            showSizeChanger: true,
            showTotal: (total) => `Total ${total} instances`,
            onChange: (page) => setPage(page),
          }}
          scroll={{ x: 1200 }}
          size="small"
        />
      </Card>
    </div>
  );
};

export default PoolDashboard;
