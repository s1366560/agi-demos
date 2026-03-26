import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Progress,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
} from 'antd';
import { Link, Plus, RefreshCw, Route, Search } from 'lucide-react';

import { AgentBindingModal } from '../../components/agent/AgentBindingModal';
import { bindingsService } from '../../services/agent/bindingsService';
import {
  useBindingError,
  useBindingLoading,
  useBindings,
  useClearBindingError,
  useDeleteBinding,
  useListBindings,
  useToggleBinding,
} from '../../stores/agentBindings';
import { useDefinitions, useListDefinitions } from '../../stores/agentDefinitions';

import type { AgentBinding, BindingTraceEntry, TestBindingResponse } from '../../types/multiAgent';
import type { ColumnsType } from 'antd/es/table';

const CHANNEL_TYPES = [
  { value: 'web', label: 'Web Chat' },
  { value: 'feishu', label: 'Feishu' },
  { value: 'dingtalk', label: 'DingTalk' },
  { value: 'wechat', label: 'WeChat' },
  { value: 'slack', label: 'Slack' },
  { value: 'api', label: 'API' },
];

export const AgentBindings: React.FC = () => {
  const { t } = useTranslation();

  const [search, setSearch] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isTestModalOpen, setIsTestModalOpen] = useState(false);
  const [testForm] = Form.useForm();
  const [testResult, setTestResult] = useState<TestBindingResponse | null>(null);
  const [showTrace, setShowTrace] = useState(false);
  const [isTestLoading, setIsTestLoading] = useState(false);

  const bindings = useBindings();
  const isLoading = useBindingLoading();
  const error = useBindingError();

  const listBindings = useListBindings();
  const deleteBinding = useDeleteBinding();
  const toggleBinding = useToggleBinding();
  const clearError = useClearBindingError();

  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  const defNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of definitions) {
      map.set(d.id, d.display_name ?? d.name);
    }
    return map;
  }, [definitions]);

  const filteredBindings = useMemo(() => {
    if (!search) return bindings;
    const lower = search.toLowerCase();
    return bindings.filter((b) => {
      const agentName = defNameMap.get(b.agent_id) ?? b.agent_id;
      return (
        agentName.toLowerCase().includes(lower) ||
        (b.channel_type ?? '').toLowerCase().includes(lower) ||
        (b.channel_id ?? '').toLowerCase().includes(lower) ||
        (b.account_id ?? '').toLowerCase().includes(lower) ||
        (b.peer_id ?? '').toLowerCase().includes(lower)
      );
    });
  }, [bindings, search, defNameMap]);

  useEffect(() => {
    listBindings();
    listDefinitions();
  }, [listBindings, listDefinitions]);

  useEffect(() => {
    if (error) message.error(error);
  }, [error]);

  useEffect(
    () => () => {
      clearError();
    },
    [clearError]
  );

  const handleToggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        await toggleBinding(id, enabled);
        message.success(enabled ? 'Binding enabled' : 'Binding disabled');
      } catch {
        // handled by store
      }
    },
    [toggleBinding]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteBinding(id);
        message.success('Binding deleted');
      } catch {
        // handled by store
      }
    },
    [deleteBinding]
  );

  const handleRefresh = useCallback(() => listBindings(), [listBindings]);

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
  }, []);

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    listBindings();
  }, [listBindings]);

  const handleTestModalOpen = useCallback(() => {
    setIsTestModalOpen(true);
    testForm.resetFields();
    setTestResult(null);
  }, [testForm]);

  const handleTestModalClose = useCallback(() => {
    setIsTestModalOpen(false);
    setTestResult(null);
  }, []);

  const handleTestSubmit = useCallback(async () => {
    try {
      const values = await testForm.validateFields();
      setIsTestLoading(true);
      const result = await bindingsService.test({
        channel_type: values.channel_type,
        channel_id: values.channel_id || undefined,
        account_id: values.account_id || undefined,
        peer_id: values.peer_id || undefined,
      });
      setTestResult(result);
    } catch (err: unknown) {
      const error = err as { errorFields?: unknown[] | undefined };
      if (!error.errorFields) {
        message.error('Failed to test routing');
      }
    } finally {
      setIsTestLoading(false);
    }
  }, [testForm]);

  const traceColumns: ColumnsType<BindingTraceEntry> = useMemo(
    () => [
      {
        title: t('tenant.agentBindings.trace.agentId', 'Agent ID'),
        dataIndex: 'agent_id',
        key: 'agent_id',
        render: (val: string) => (
          <Tooltip title={val}>
            <span className="font-mono text-xs">{val.slice(0, 8)}</span>
          </Tooltip>
        ),
      },
      {
        title: t('tenant.agentBindings.trace.specificity', 'Score'),
        dataIndex: 'specificity_score',
        key: 'specificity_score',
        render: (val: number, record: BindingTraceEntry) => (
          <span className={record.selected ? 'font-bold' : ''}>{val}</span>
        ),
      },
      {
        title: t('tenant.agentBindings.trace.priority', 'Priority'),
        dataIndex: 'priority',
        key: 'priority',
      },
      {
        title: t('tenant.agentBindings.trace.channelType', 'Channel Type'),
        dataIndex: 'channel_type',
        key: 'channel_type',
        render: (val: string | null) => val ?? '—',
      },
      {
        title: t('tenant.agentBindings.trace.matchCriteria', 'Match Criteria'),
        key: 'criteria',
        render: (_: unknown, record: BindingTraceEntry) => {
          const criteria = [];
          if (record.channel_id)
            criteria.push(
              `${t('tenant.agentBindings.trace.channel', 'Channel')}: ${record.channel_id}`
            );
          if (record.account_id)
            criteria.push(
              `${t('tenant.agentBindings.trace.account', 'Account')}: ${record.account_id}`
            );
          if (record.peer_id)
            criteria.push(`${t('tenant.agentBindings.trace.peer', 'Peer')}: ${record.peer_id}`);
          return criteria.length > 0 ? (
            <span className="text-xs">{criteria.join(', ')}</span>
          ) : (
            <span className="text-xs text-slate-400">—</span>
          );
        },
      },
      {
        title: t('tenant.agentBindings.trace.status', 'Status'),
        key: 'status',
        render: (_: unknown, record: BindingTraceEntry) => {
          if (record.selected) {
            return (
              <Tag
                color="success"
                className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-green-200 dark:border-green-800"
              >
                {t('common.selected', 'Selected')}
              </Tag>
            );
          }
          if (record.eliminated) {
            return (
              <Tooltip title={record.elimination_reason}>
                <Tag color="error" className="cursor-help">
                  {t('common.eliminated', 'Eliminated')}
                </Tag>
              </Tooltip>
            );
          }
          return <Tag>{t('common.evaluated', 'Evaluated')}</Tag>;
        },
      },
    ],
    [t]
  );

  const columns: ColumnsType<AgentBinding> = useMemo(
    () => [
      {
        title: t('tenant.agentBindings.columns.agent', 'Agent'),
        dataIndex: 'agent_id',
        key: 'agent',
        render: (agentId: string) => (
          <span className="font-medium text-sm">{defNameMap.get(agentId) ?? agentId}</span>
        ),
      },
      {
        title: t('tenant.agentBindings.columns.channelType', 'Channel Type'),
        dataIndex: 'channel_type',
        key: 'channel_type',
        render: (val: string | null) => (val ? <Tag>{val}</Tag> : <Tag color="default">Any</Tag>),
      },
      {
        title: t('tenant.agentBindings.columns.channelId', 'Channel ID'),
        dataIndex: 'channel_id',
        key: 'channel_id',
        render: (val: string | null) => (
          <span className="text-xs text-slate-500 dark:text-slate-400">{val ?? '-'}</span>
        ),
      },
      {
        title: t('tenant.agentBindings.columns.accountId', 'Account ID'),
        dataIndex: 'account_id',
        key: 'account_id',
        render: (val: string | null) => (
          <span className="text-xs text-slate-500 dark:text-slate-400">{val ?? '-'}</span>
        ),
      },
      {
        title: t('tenant.agentBindings.columns.peerId', 'Peer ID'),
        dataIndex: 'peer_id',
        key: 'peer_id',
        render: (val: string | null) => (
          <span className="text-xs text-slate-500 dark:text-slate-400">{val ?? '-'}</span>
        ),
      },
      {
        title: t('tenant.agentBindings.columns.specificity', 'Specificity'),
        dataIndex: 'specificity_score',
        key: 'specificity_score',
        width: 100,
        align: 'center' as const,
        sorter: (a: AgentBinding, b: AgentBinding) =>
          (b.specificity_score ?? 0) - (a.specificity_score ?? 0),
        render: (val: number) => (
          <Tag color={val >= 6 ? 'green' : val >= 3 ? 'gold' : 'default'}>{val}</Tag>
        ),
      },
      {
        title: t('tenant.agentBindings.columns.priority', 'Priority'),
        dataIndex: 'priority',
        key: 'priority',
        width: 90,
        align: 'center' as const,
        sorter: (a: AgentBinding, b: AgentBinding) => b.priority - a.priority,
      },
      {
        title: t('tenant.agentBindings.columns.enabled', 'Enabled'),
        dataIndex: 'enabled',
        key: 'enabled',
        width: 80,
        align: 'center' as const,
        render: (_: boolean, record: AgentBinding) => (
          <Switch
            size="small"
            checked={record.enabled}
            onChange={(checked) => handleToggle(record.id, checked)}
          />
        ),
      },
      {
        title: '',
        key: 'actions',
        width: 60,
        render: (_: unknown, record: AgentBinding) => (
          <Popconfirm
            title="Delete this binding?"
            onConfirm={() => handleDelete(record.id)}
            okText="Delete"
            cancelText="Cancel"
          >
            <button
              type="button"
              className="text-slate-400 hover:text-red-500 transition-colors text-xs"
            >
              {t('common.delete', 'Delete')}
            </button>
          </Popconfirm>
        ),
      },
    ],
    [defNameMap, handleToggle, handleDelete, t]
  );

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-5 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.agentBindings.title', 'Agent Bindings')}
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {t(
              'tenant.agentBindings.subtitle',
              'Bind agents to channels to control which agent handles which conversations'
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleTestModalOpen}
            className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
          >
            <Route size={16} />
            {t('tenant.agentBindings.testRouting', 'Test Routing')}
          </button>
          <button
            type="button"
            onClick={() => {
              setIsModalOpen(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
          >
            <Plus size={16} />
            {t('tenant.agentBindings.createNew', 'Create Binding')}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-4 text-sm text-slate-600 dark:text-slate-400">
        <span>
          {bindings.length} {bindings.length === 1 ? 'binding' : 'bindings'}
        </span>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
            placeholder={t('common.search', 'Search...')}
            className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
          />
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          <RefreshCw size={16} />
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin size="large" />
        </div>
      ) : filteredBindings.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-slate-500 dark:text-slate-400">
          <Link size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-lg font-medium">
            {search
              ? t('tenant.agentBindings.noResults', 'No bindings match your search')
              : t('tenant.agentBindings.empty', 'No agent bindings yet')}
          </p>
          {!search && (
            <button
              type="button"
              onClick={() => {
                setIsModalOpen(true);
              }}
              className="mt-4 text-primary hover:underline text-sm"
            >
              {t('tenant.agentBindings.createFirst', 'Create your first binding')}
            </button>
          )}
        </div>
      ) : (
        <Table<AgentBinding>
          dataSource={filteredBindings}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          className="dark:[&_.ant-table]:bg-slate-800"
        />
      )}

      <AgentBindingModal
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
      />

      {/* Test Routing Modal */}
      <Modal
        title={t('tenant.agentBindings.testRouting.title', 'Test Routing Resolution')}
        open={isTestModalOpen}
        onCancel={handleTestModalClose}
        onOk={handleTestSubmit}
        okText={t('tenant.agentBindings.testRouting.test', 'Test')}
        cancelText={t('common.cancel', 'Cancel')}
        confirmLoading={isTestLoading}
        width={500}
        destroyOnHidden
      >
        <Form form={testForm} layout="vertical" className="mt-4">
          <Form.Item
            name="channel_type"
            label={t('tenant.agentBindings.testRouting.channelType', 'Channel Type')}
            rules={[
              {
                required: true,
                message: t(
                  'tenant.agentBindings.testRouting.channelTypeRequired',
                  'Please select a channel type'
                ),
              },
            ]}
          >
            <select className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100">
              <option value="">
                {t('tenant.agentBindings.testRouting.selectChannelType', 'Select channel type')}
              </option>
              {CHANNEL_TYPES.map((ct) => (
                <option key={ct.value} value={ct.value}>
                  {ct.label}
                </option>
              ))}
            </select>
          </Form.Item>

          <Form.Item
            name="channel_id"
            label={t('tenant.agentBindings.testRouting.channelId', 'Channel ID')}
          >
            <Input
              placeholder={t(
                'tenant.agentBindings.testRouting.channelIdPlaceholder',
                'Optional: specific channel identifier'
              )}
            />
          </Form.Item>

          <Form.Item
            name="account_id"
            label={t('tenant.agentBindings.testRouting.accountId', 'Account ID')}
          >
            <Input
              placeholder={t(
                'tenant.agentBindings.testRouting.accountIdPlaceholder',
                'Optional: user account identifier'
              )}
            />
          </Form.Item>

          <Form.Item name="peer_id" label={t('tenant.agentBindings.testRouting.peerId', 'Peer ID')}>
            <Input
              placeholder={t(
                'tenant.agentBindings.testRouting.peerIdPlaceholder',
                'Optional: peer identifier'
              )}
            />
          </Form.Item>
        </Form>

        {/* Test Result Display */}
        {testResult && (
          <div className="mt-4 p-4 bg-slate-50 dark:bg-slate-800 rounded-lg">
            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
              {t('tenant.agentBindings.testRouting.result', 'Routing Result')}
            </h4>
            {testResult.matched ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-600 dark:text-slate-400">
                    {t('tenant.agentBindings.testRouting.matchedAgent', 'Matched Agent')}
                  </span>
                  <Tag color="green">{testResult.agent_name ?? testResult.agent_id}</Tag>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-600 dark:text-slate-400">
                    {t('tenant.agentBindings.testRouting.specificity', 'Specificity Score')}
                  </span>
                  <span className="text-sm font-mono">{testResult.specificity_score}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-600 dark:text-slate-400">
                    {t('tenant.agentBindings.testRouting.confidence', 'Confidence')}
                  </span>
                  <Progress
                    percent={testResult.confidence * 100}
                    size="small"
                    className="flex-1"
                    strokeColor={{
                      '0%': '#ff7a45',
                      '50%': '#52c41a',
                      '100%': '#1890ff',
                    }}
                    format={(percent) => `${percent?.toFixed(0)}%`}
                  />
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center py-4 text-slate-500 dark:text-slate-400">
                <Route size={32} className="mb-2 text-slate-300 dark:text-slate-600" />
                <p className="text-sm">
                  {t(
                    'tenant.agentBindings.testRouting.noMatch',
                    'No matching binding found for this context'
                  )}
                </p>
              </div>
            )}

            <div className="mt-6 border-t border-slate-200 dark:border-slate-700 pt-4">
              <button
                type="button"
                className="text-sm font-medium text-primary hover:underline flex items-center gap-1"
                onClick={() => {
                  setShowTrace(!showTrace);
                }}
              >
                {showTrace
                  ? t('tenant.agentBindings.trace.hide', 'Hide Decision Trace')
                  : t('tenant.agentBindings.trace.show', 'Show Decision Trace')}
                {testResult.trace && (
                  <span className="text-slate-500 text-xs font-normal ml-1">
                    (
                    {t('tenant.agentBindings.trace.candidatesCount', '{{count}} candidates', {
                      count: testResult.trace.length,
                    })}
                    )
                  </span>
                )}
              </button>

              {showTrace && testResult.trace && (
                <div className="mt-3 overflow-x-auto">
                  <Table<BindingTraceEntry>
                    dataSource={testResult.trace}
                    columns={traceColumns}
                    rowKey="binding_id"
                    size="small"
                    pagination={false}
                    className="dark:[&_.ant-table]:bg-slate-800"
                    rowClassName={(record) => {
                      if (record.selected) {
                        return 'bg-green-50 dark:bg-green-900/20';
                      }
                      if (record.eliminated) {
                        return 'opacity-60 grayscale';
                      }
                      return '';
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default AgentBindings;
