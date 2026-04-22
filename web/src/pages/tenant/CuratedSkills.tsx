/**
 * Curated Skills page (P2-4).
 *
 * Two tabs:
 *   1. "精选库" — list of admin-approved curated skills with Fork action.
 *   2. "我的提交" — caller's submission history (status + reviewer note).
 *
 * P2-4 Track D additions:
 *   - Curated rows are grouped by ``source_skill_id`` so multiple versions
 *     of the same skill collapse into a single row with a version selector.
 *   - "包含已弃用版本" toggle surfaces deprecated rows when enabled.
 *   - Pending submissions expose "撤回" action (submitter-only).
 *
 * Submitting a private skill for review lives on the SkillList page; this
 * page is the read side for tenants.
 */

import { useMemo, useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Empty,
  List,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { GitFork, Library, Undo2 } from 'lucide-react';

import {
  curatedSkillAPI,
  type CuratedSkill,
  type SkillSubmission,
} from '@/services/curatedSkillService';

const { Text, Title, Paragraph } = Typography;

function statusColor(status: string): string {
  switch (status) {
    case 'pending':
      return 'orange';
    case 'approved':
      return 'green';
    case 'rejected':
      return 'red';
    case 'withdrawn':
      return 'default';
    default:
      return 'default';
  }
}

function semverCompareDesc(a: string, b: string): number {
  const pa = a.split('.').map((x) => parseInt(x, 10) || 0);
  const pb = b.split('.').map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < 3; i += 1) {
    const da = pa[i] ?? 0;
    const db = pb[i] ?? 0;
    if (da !== db) return db - da;
  }
  return 0;
}

interface VersionGroup {
  key: string;
  versions: CuratedSkill[];
}

/** Group curated rows by source_skill_id (fallback: unique row key) and
 *  sort each group's versions newest-first by semver. */
function groupBySource(items: CuratedSkill[]): VersionGroup[] {
  const map = new Map<string, CuratedSkill[]>();
  items.forEach((c) => {
    const key = c.source_skill_id ?? `__orphan__:${c.id}`;
    const arr = map.get(key) ?? [];
    arr.push(c);
    map.set(key, arr);
  });
  return Array.from(map.entries())
    .map(([key, versions]) => ({
      key,
      versions: [...versions].sort((a, b) => semverCompareDesc(a.semver, b.semver)),
    }))
    .sort((a, b) => {
      const ta = a.versions[0]?.created_at ?? '';
      const tb = b.versions[0]?.created_at ?? '';
      return tb.localeCompare(ta);
    });
}

function ForkDialog({
  curated,
  open,
  onClose,
}: {
  curated: CuratedSkill | null;
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [includeTriggers, setIncludeTriggers] = useState(true);
  const [includeExecutor, setIncludeExecutor] = useState(true);
  const [includeMetadata, setIncludeMetadata] = useState(true);

  const mutation = useMutation({
    mutationFn: () => {
      if (!curated) throw new Error('no curated skill');
      return curatedSkillAPI.fork(curated.id, {
        include_triggers: includeTriggers,
        include_executor: includeExecutor,
        include_metadata: includeMetadata,
      });
    },
    onSuccess: (result) => {
      message.success(`Forked. New skill id: ${result.skill_id}`);
      void qc.invalidateQueries({ queryKey: ['skills'] });
      onClose();
    },
    onError: (err: Error) => {
      message.error(err.message || 'Fork failed');
    },
  });

  return (
    <Modal
      title={curated ? `Fork "${(curated.payload.name as string) ?? 'skill'}" v${curated.semver}` : 'Fork'}
      open={open}
      onCancel={onClose}
      onOk={() => {
        mutation.mutate();
      }}
      okText="Fork"
      confirmLoading={mutation.isPending}
    >
      <Space direction="vertical" className="w-full">
        <Text type="secondary">选择复制到私有库时要包含的内容：</Text>
        <Checkbox
          checked={includeTriggers}
          onChange={(e) => {
            setIncludeTriggers(e.target.checked);
          }}
        >
          触发模式 (trigger patterns)
        </Checkbox>
        <Checkbox
          checked={includeExecutor}
          onChange={(e) => {
            setIncludeExecutor(e.target.checked);
          }}
        >
          执行器（tools + prompt_template + full_content）
        </Checkbox>
        <Checkbox
          checked={includeMetadata}
          onChange={(e) => {
            setIncludeMetadata(e.target.checked);
          }}
        >
          元数据 (metadata)
        </Checkbox>
      </Space>
    </Modal>
  );
}

function VersionedCuratedRow({
  group,
  onFork,
}: {
  group: VersionGroup;
  onFork: (c: CuratedSkill) => void;
}) {
  const [selectedId, setSelectedId] = useState<string>(group.versions[0]!.id);
  const selected =
    group.versions.find((v) => v.id === selectedId) ?? group.versions[0]!;
  const hasMultiple = group.versions.length > 1;
  const name = (selected.payload.name as string) ?? 'Unnamed skill';
  const description = (selected.payload.description as string) ?? '';
  const isDeprecated = selected.status === 'deprecated';

  return (
    <List.Item
      actions={[
        <Button
          key="fork"
          type="primary"
          icon={<GitFork size={14} />}
          onClick={() => {
            onFork(selected);
          }}
          disabled={isDeprecated}
        >
          Fork 到私有库
        </Button>,
      ]}
    >
      <List.Item.Meta
        avatar={<Library size={20} />}
        title={
          <Space wrap>
            <span>{name}</span>
            {hasMultiple ? (
              <Select
                size="small"
                value={selectedId}
                onChange={setSelectedId}
                style={{ minWidth: 110 }}
                options={group.versions.map((v) => ({
                  value: v.id,
                  label: `v${v.semver}${v.status === 'deprecated' ? '（已弃用）' : ''}`,
                }))}
              />
            ) : (
              <Tag color={isDeprecated ? 'default' : 'blue'}>v{selected.semver}</Tag>
            )}
            {isDeprecated ? <Tag>已弃用</Tag> : null}
          </Space>
        }
        description={
          <Space direction="vertical" size={2}>
            <Paragraph type="secondary" ellipsis={{ rows: 2 }} className="!mb-0">
              {description}
            </Paragraph>
            <Text type="secondary" className="text-xs">
              hash: <code>{selected.revision_hash.slice(0, 12)}</code>
              {hasMultiple ? ` · ${group.versions.length} 个版本` : ''}
            </Text>
          </Space>
        }
      />
    </List.Item>
  );
}

function CuratedTab() {
  const [includeDeprecated, setIncludeDeprecated] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ['skills', 'curated', { includeDeprecated }],
    queryFn: () => curatedSkillAPI.list({ include_deprecated: includeDeprecated }),
  });
  const [forkTarget, setForkTarget] = useState<CuratedSkill | null>(null);

  const groups = useMemo(() => groupBySource(data ?? []), [data]);

  if (isLoading) return <Skeleton active paragraph={{ rows: 4 }} />;

  return (
    <>
      <Space className="mb-3">
        <Switch
          size="small"
          checked={includeDeprecated}
          onChange={setIncludeDeprecated}
        />
        <Text type="secondary">包含已弃用版本</Text>
      </Space>
      {groups.length === 0 ? (
        <Empty description="精选库暂无已发布的 Skill" />
      ) : (
        <List
          dataSource={groups}
          renderItem={(group) => (
            <VersionedCuratedRow
              key={group.key}
              group={group}
              onFork={setForkTarget}
            />
          )}
        />
      )}
      <ForkDialog
        curated={forkTarget}
        open={forkTarget !== null}
        onClose={() => {
          setForkTarget(null);
        }}
      />
    </>
  );
}

function SubmissionsTab() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['skills', 'submissions', 'mine'],
    queryFn: () => curatedSkillAPI.listMySubmissions(),
  });

  const withdrawMutation = useMutation({
    mutationFn: (id: string) => curatedSkillAPI.withdrawSubmission(id),
    onSuccess: () => {
      message.success('已撤回提交');
      void qc.invalidateQueries({ queryKey: ['skills', 'submissions', 'mine'] });
    },
    onError: (err: Error) => {
      message.error(err.message || '撤回失败');
    },
  });

  if (isLoading) return <Skeleton active paragraph={{ rows: 4 }} />;

  const items = data ?? [];
  if (items.length === 0) {
    return <Empty description="暂无提交记录" />;
  }

  return (
    <List
      dataSource={items}
      renderItem={(s: SkillSubmission) => {
        const name = (s.skill_snapshot.name as string) ?? 'Unnamed';
        const isPending = s.status === 'pending';
        return (
          <List.Item
            actions={
              isPending
                ? [
                    <Popconfirm
                      key="withdraw"
                      title="撤回此提交？"
                      description="撤回后状态变为 withdrawn，不再进入审核队列。"
                      okText="撤回"
                      cancelText="取消"
                      onConfirm={() => {
                        withdrawMutation.mutate(s.id);
                      }}
                    >
                      <Button
                        size="small"
                        icon={<Undo2 size={14} />}
                        loading={withdrawMutation.isPending}
                      >
                        撤回
                      </Button>
                    </Popconfirm>,
                  ]
                : []
            }
          >
            <List.Item.Meta
              title={
                <Space>
                  <span>{name}</span>
                  <Tag color="blue">v{s.proposed_semver}</Tag>
                  <Badge status={statusColor(s.status) as never} text={s.status} />
                </Space>
              }
              description={
                <Space direction="vertical" size={2}>
                  {s.submission_note ? (
                    <Text type="secondary">备注：{s.submission_note}</Text>
                  ) : null}
                  {s.review_note ? (
                    <Text type={s.status === 'rejected' ? 'danger' : 'secondary'}>
                      审核意见：{s.review_note}
                    </Text>
                  ) : null}
                  <Text type="secondary" className="text-xs">
                    submitted {new Date(s.created_at).toLocaleString()}
                  </Text>
                </Space>
              }
            />
          </List.Item>
        );
      }}
    />
  );
}

export default function CuratedSkills() {
  return (
    <Card className="max-w-5xl mx-auto">
      <Title level={3}>精选 Skill 库</Title>
      <Paragraph type="secondary">
        精选库包含管理员审核通过的 Skill 模板，所有租户都可以 fork 到自己的私有库进行修改。
      </Paragraph>
      <Tabs
        items={[
          { key: 'curated', label: '精选库', children: <CuratedTab /> },
          { key: 'submissions', label: '我的提交', children: <SubmissionsTab /> },
        ]}
      />
    </Card>
  );
}
