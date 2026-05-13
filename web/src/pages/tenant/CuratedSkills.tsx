/**
 * Curated Skills page (P2-4).
 *
 * Tenants can fork approved skill snapshots and review their own submissions.
 */

import { useMemo, useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Button,
  Checkbox,
  Empty,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
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

const { Text, Paragraph } = Typography;

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';

function statusTagColor(status: string): string {
  switch (status) {
    case 'pending':
      return 'orange';
    case 'approved':
    case 'active':
      return 'green';
    case 'rejected':
      return 'red';
    case 'withdrawn':
    case 'deprecated':
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

function groupBySource(items: CuratedSkill[]): VersionGroup[] {
  const map = new Map<string, CuratedSkill[]>();
  items.forEach((curated) => {
    const key = curated.source_skill_id ?? `__orphan__:${curated.id}`;
    const versions = map.get(key) ?? [];
    map.set(key, [...versions, curated]);
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
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [includeExecutor, setIncludeExecutor] = useState(true);
  const [includeMetadata, setIncludeMetadata] = useState(true);

  const mutation = useMutation({
    mutationFn: () => {
      if (!curated) throw new Error('no curated skill');
      return curatedSkillAPI.fork(curated.id, {
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

  const name = curated ? (curated.payload.name as string) : 'skill';

  return (
    <Modal
      title={curated ? `Fork "${name}" v${curated.semver}` : 'Fork'}
      open={open}
      onCancel={onClose}
      onOk={() => {
        mutation.mutate();
      }}
      okText="Fork"
      confirmLoading={mutation.isPending}
    >
      <div className="space-y-4">
        <Text type="secondary">{t('skill.curated.forkDialogContent')}</Text>
        <div className={`rounded-[6px] p-3 ${surface}`}>
          <Checkbox
            checked={includeExecutor}
            onChange={(e) => {
              setIncludeExecutor(e.target.checked);
            }}
          >
            {t('skill.curated.forkIncludeExecutor')}
          </Checkbox>
          <div className="mt-3">
            <Checkbox
              checked={includeMetadata}
              onChange={(e) => {
                setIncludeMetadata(e.target.checked);
              }}
            >
              {t('skill.curated.forkIncludeMetadata')}
            </Checkbox>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function VersionedCuratedRow({
  group,
  onFork,
}: {
  group: VersionGroup;
  onFork: (curated: CuratedSkill) => void;
}) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string>(group.versions[0]?.id ?? '');
  const selected = group.versions.find((version) => version.id === selectedId) ?? group.versions[0];

  if (!selected) {
    return null;
  }

  const hasMultiple = group.versions.length > 1;
  const name = selected.payload.name as string;
  const description = selected.payload.description as string;
  const isDeprecated = selected.status === 'deprecated';

  return (
    <div className="grid gap-4 border-b border-[oklch(0.9_0.006_255)] px-4 py-4 last:border-b-0 dark:border-[oklch(0.28_0.006_255)] md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] text-[oklch(0.4_0.01_255)] dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.23_0.005_255)] dark:text-[oklch(0.76_0.006_255)]">
            <Library size={16} />
          </span>
          <span className={`truncate text-sm font-semibold ${pageText}`}>{name}</span>
          {hasMultiple ? (
            <Select
              size="small"
              value={selected.id}
              onChange={setSelectedId}
              style={{ minWidth: 116 }}
              options={group.versions.map((version) => ({
                value: version.id,
                label: `v${version.semver}${version.status === 'deprecated' ? t('skill.curated.deprecatedSuffix') : ''}`,
              }))}
            />
          ) : (
            <Tag color={isDeprecated ? 'default' : 'blue'}>v{selected.semver}</Tag>
          )}
          <Tag color={statusTagColor(selected.status)}>{selected.status}</Tag>
        </div>
        <Paragraph type="secondary" ellipsis={{ rows: 2 }} className="!mb-0 !mt-2">
          {description}
        </Paragraph>
        <div className={`mt-2 text-xs ${mutedText}`}>
          hash <code>{selected.revision_hash.slice(0, 12)}</code>
          {hasMultiple ? t('skill.curated.versionCount', { count: group.versions.length }) : ''}
        </div>
      </div>
      <Button
        type="primary"
        icon={<GitFork size={14} />}
        onClick={() => {
          onFork(selected);
        }}
        disabled={isDeprecated}
      >
        {t('skill.curated.forkButton')}
      </Button>
    </div>
  );
}

function CuratedTab() {
  const { t } = useTranslation();
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
      <div className="mb-3 flex items-center justify-between gap-3">
        <Text type="secondary">{t('skill.curated.publishedCount', { count: groups.length })}</Text>
        <span className="inline-flex items-center gap-2 text-sm text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]">
          <Switch
            size="small"
            checked={includeDeprecated}
            onChange={setIncludeDeprecated}
            aria-label={t('skill.curated.includeDeprecatedAria')}
          />
          {t('skill.curated.includeDeprecatedLabel')}
        </span>
      </div>
      {groups.length === 0 ? (
        <div className={`rounded-[6px] py-12 ${surface}`}>
          <Empty description={t('skill.curated.emptyCurated')} />
        </div>
      ) : (
        <div className={`overflow-hidden rounded-[6px] ${surface}`}>
          {groups.map((group) => (
            <VersionedCuratedRow key={group.key} group={group} onFork={setForkTarget} />
          ))}
        </div>
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

function SubmissionRow({ submission }: { submission: SkillSubmission }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const withdrawMutation = useMutation({
    mutationFn: (id: string) => curatedSkillAPI.withdrawSubmission(id),
    onSuccess: () => {
      message.success(t('skill.curated.withdrawSuccess'));
      void qc.invalidateQueries({ queryKey: ['skills', 'submissions', 'mine'] });
    },
    onError: (err: Error) => {
      message.error(err.message || t('skill.curated.withdrawFailed'));
    },
  });
  const name = submission.skill_snapshot.name as string;
  const isPending = submission.status === 'pending';

  return (
    <div className="grid gap-3 border-b border-[oklch(0.9_0.006_255)] px-4 py-4 last:border-b-0 dark:border-[oklch(0.28_0.006_255)] md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-sm font-semibold ${pageText}`}>{name}</span>
          <Tag color="blue">v{submission.proposed_semver}</Tag>
          <Tag color={statusTagColor(submission.status)}>{submission.status}</Tag>
        </div>
        <div className="mt-2 space-y-1">
          {submission.submission_note ? (
            <div className={`text-sm ${mutedText}`}>
              {t('skill.curated.noteLabel')}
              {submission.submission_note}
            </div>
          ) : null}
          {submission.review_note ? (
            <div
              className={
                submission.status === 'rejected'
                  ? 'text-sm text-[oklch(0.55_0.18_25)]'
                  : `text-sm ${mutedText}`
              }
            >
              {t('skill.curated.reviewNoteLabel')}
              {submission.review_note}
            </div>
          ) : null}
          <div className={`text-xs ${mutedText}`}>
            submitted {new Date(submission.created_at).toLocaleString()}
          </div>
        </div>
      </div>
      {isPending ? (
        <Popconfirm
          title={t('skill.curated.withdrawConfirmTitle')}
          description={t('skill.curated.withdrawConfirmDescription')}
          okText={t('skill.curated.withdrawOk')}
          cancelText={t('skill.curated.withdrawCancel')}
          onConfirm={() => {
            withdrawMutation.mutate(submission.id);
          }}
        >
          <Button size="small" icon={<Undo2 size={14} />} loading={withdrawMutation.isPending}>
            {t('skill.curated.withdrawAction')}
          </Button>
        </Popconfirm>
      ) : null}
    </div>
  );
}

function SubmissionsTab() {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['skills', 'submissions', 'mine'],
    queryFn: () => curatedSkillAPI.listMySubmissions(),
  });

  if (isLoading) return <Skeleton active paragraph={{ rows: 4 }} />;

  const items = data ?? [];
  if (items.length === 0) {
    return (
      <div className={`rounded-[6px] py-12 ${surface}`}>
        <Empty description={t('skill.curated.emptySubmissions')} />
      </div>
    );
  }

  return (
    <div className={`overflow-hidden rounded-[6px] ${surface}`}>
      {items.map((submission) => (
        <SubmissionRow key={submission.id} submission={submission} />
      ))}
    </div>
  );
}

export default function CuratedSkills() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <div>
        <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>Library</div>
        <h1 className={`mt-2 text-2xl font-semibold leading-8 tracking-normal ${pageText}`}>
          {t('skill.curated.pageTitle')}
        </h1>
        <p className={`mt-1 max-w-3xl text-sm ${mutedText}`}>
          {t('skill.curated.pageDescription')}
        </p>
      </div>
      <div className={`rounded-[6px] p-3 ${surface}`}>
        <Tabs
          items={[
            { key: 'curated', label: t('skill.curated.tabCurated'), children: <CuratedTab /> },
            { key: 'submissions', label: t('skill.curated.tabSubmissions'), children: <SubmissionsTab /> },
          ]}
        />
      </div>
    </div>
  );
}
