/**
 * Admin Skill Review page (P2-4).
 *
 * Superuser-only queue for reviewing tenant-submitted skill candidates.
 * Approving publishes the snapshot to ``curated_skills``; rejecting records
 * a note and closes the submission.
 */

import { useState } from 'react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Empty, Input, Modal, Radio, Skeleton, Tabs, Tag, Typography, message } from 'antd';
import { Check, X } from 'lucide-react';

import {
  curatedSkillAPI,
  type SemverBump,
  type SkillSubmission,
} from '@/services/curatedSkillService';

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;

type StatusFilter = 'pending' | 'approved' | 'rejected' | 'withdrawn';

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';

function statusTagColor(status: string): string {
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

/** Preview next semver without contacting the server. Backend is the
 *  source of truth; this keeps the dialog snappy. */
function previewNextSemver(prior: string | null, bump: SemverBump): string {
  if (!prior) return '0.1.0';
  const parts = prior.split('.').map((x) => parseInt(x, 10) || 0);
  const ma = parts[0] ?? 0;
  const mi = parts[1] ?? 0;
  const pa = parts[2] ?? 0;
  if (bump === 'major') return `${String(ma + 1)}.0.0`;
  if (bump === 'minor') return `${String(ma)}.${String(mi + 1)}.0`;
  return `${String(ma)}.${String(mi)}.${String(pa + 1)}`;
}

function ReviewDialog({
  submission,
  mode,
  open,
  onClose,
}: {
  submission: SkillSubmission | null;
  mode: 'approve' | 'reject';
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const [bump, setBump] = useState<SemverBump | 'trust'>('trust');

  const mutation = useMutation({
    mutationFn: async () => {
      if (!submission) throw new Error('no submission');
      if (mode === 'approve') {
        const body = {
          review_note: note || null,
          bump: bump === 'trust' ? null : bump,
        };
        return curatedSkillAPI.adminApprove(submission.id, body);
      }
      return curatedSkillAPI.adminReject(submission.id, { review_note: note || null });
    },
    onSuccess: () => {
      message.success(mode === 'approve' ? 'Submission approved' : 'Submission rejected');
      void qc.invalidateQueries({ queryKey: ['admin', 'skill-submissions'] });
      setNote('');
      setBump('trust');
      onClose();
    },
    onError: (err: Error) => {
      message.error(err.message || 'Review failed');
    },
  });

  const effectiveSemver =
    submission === null
      ? ''
      : bump === 'trust'
        ? submission.proposed_semver
        : previewNextSemver(submission.proposed_semver, bump);

  return (
    <Modal
      title={mode === 'approve' ? '通过审核' : '驳回提交'}
      open={open}
      onCancel={() => {
        setNote('');
        setBump('trust');
        onClose();
      }}
      onOk={() => {
        mutation.mutate();
      }}
      okText={mode === 'approve' ? 'Approve' : 'Reject'}
      okButtonProps={{ danger: mode === 'reject' }}
      confirmLoading={mutation.isPending}
    >
      <div className="space-y-4">
        <Text type="secondary">
          {mode === 'approve'
            ? '审核通过将把此 Skill 快照发布到精选库。'
            : '驳回提交将关闭此记录并记录你的审核意见。'}
        </Text>
        {mode === 'approve' ? (
          <div className={`space-y-2 rounded-[6px] p-3 ${surface}`}>
            <Text strong>发布版本号</Text>
            <Radio.Group
              value={bump}
              onChange={(e) => {
                setBump(e.target.value as SemverBump | 'trust');
              }}
            >
              <Radio value="trust">沿用提交者版本 (v{submission?.proposed_semver ?? '-'})</Radio>
              <Radio value="patch">覆盖为 patch</Radio>
              <Radio value="minor">覆盖为 minor</Radio>
              <Radio value="major">覆盖为 major</Radio>
            </Radio.Group>
            <Text type="secondary" className="text-xs">
              最终发布版本：<Tag color="blue">v{effectiveSemver}</Tag>
              <span className="ml-2">
                （若同一来源已有激活版本，旧版本会自动标记为 deprecated）
              </span>
            </Text>
          </div>
        ) : null}
        <TextArea
          rows={4}
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder="审核意见（可选）"
          maxLength={2000}
          showCount
        />
      </div>
    </Modal>
  );
}

function SubmissionRow({
  submission,
  onReview,
}: {
  submission: SkillSubmission;
  onReview: (s: SkillSubmission, mode: 'approve' | 'reject') => void;
}) {
  const name = submission.skill_snapshot.name as string;
  const description = submission.skill_snapshot.description as string;
  const isPending = submission.status === 'pending';

  return (
    <div className="grid gap-4 border-b border-[oklch(0.9_0.006_255)] px-4 py-4 last:border-b-0 dark:border-[oklch(0.28_0.006_255)] lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-sm font-semibold ${pageText}`}>{name}</span>
          <Tag color="blue">v{submission.proposed_semver}</Tag>
          <Tag color={statusTagColor(submission.status)}>{submission.status}</Tag>
        </div>
        <Paragraph type="secondary" ellipsis={{ rows: 2 }} className="!mb-0 !mt-2">
          {description}
        </Paragraph>
        <div className={`mt-2 text-xs ${mutedText}`}>
          tenant <code>{submission.submitter_tenant_id}</code> · submitted{' '}
          {new Date(submission.created_at).toLocaleString()}
        </div>
        {submission.submission_note ? (
          <div className={`mt-2 text-sm ${mutedText}`}>提交备注：{submission.submission_note}</div>
        ) : null}
        {submission.review_note ? (
          <div
            className={
              submission.status === 'rejected'
                ? 'mt-2 text-sm text-[oklch(0.55_0.18_25)]'
                : `mt-2 text-sm ${mutedText}`
            }
          >
            审核意见：{submission.review_note}
          </div>
        ) : null}
      </div>
      {isPending ? (
        <div className="flex flex-wrap gap-2">
          <Button
            type="primary"
            icon={<Check size={14} />}
            onClick={() => {
              onReview(submission, 'approve');
            }}
          >
            Approve
          </Button>
          <Button
            danger
            icon={<X size={14} />}
            onClick={() => {
              onReview(submission, 'reject');
            }}
          >
            Reject
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function SubmissionsList({ status }: { status: StatusFilter }) {
  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'skill-submissions', status],
    queryFn: () => curatedSkillAPI.adminList(status),
  });

  const [active, setActive] = useState<{
    submission: SkillSubmission;
    mode: 'approve' | 'reject';
  } | null>(null);

  if (isLoading) return <Skeleton active paragraph={{ rows: 4 }} />;

  const items = data ?? [];
  if (items.length === 0) {
    return (
      <div className={`rounded-[6px] py-12 ${surface}`}>
        <Empty description={`暂无 ${status} 的提交`} />
      </div>
    );
  }

  return (
    <>
      <div className={`overflow-hidden rounded-[6px] ${surface}`}>
        {items.map((s) => (
          <SubmissionRow
            key={s.id}
            submission={s}
            onReview={(sub, mode) => {
              setActive({ submission: sub, mode });
            }}
          />
        ))}
      </div>
      <ReviewDialog
        submission={active?.submission ?? null}
        mode={active?.mode ?? 'approve'}
        open={active !== null}
        onClose={() => {
          setActive(null);
        }}
      />
    </>
  );
}

export default function AdminSkillReview() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <div>
        <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>
          Admin Review
        </div>
        <Title level={3} className={`!mb-1 !mt-2 ${pageText}`}>
          Skill 审核（管理员）
        </Title>
        <Paragraph type="secondary" className="!mb-0 max-w-3xl">
          审核由租户提交的 Skill 候选。通过后会以当前版本号发布到精选库；驳回会记录审核意见。
        </Paragraph>
      </div>
      <div className={`rounded-[6px] p-3 ${surface}`}>
        <Tabs
          defaultActiveKey="pending"
          items={[
            { key: 'pending', label: '待审核', children: <SubmissionsList status="pending" /> },
            { key: 'approved', label: '已通过', children: <SubmissionsList status="approved" /> },
            { key: 'rejected', label: '已驳回', children: <SubmissionsList status="rejected" /> },
            { key: 'withdrawn', label: '已撤回', children: <SubmissionsList status="withdrawn" /> },
          ]}
        />
      </div>
    </div>
  );
}
