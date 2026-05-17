/**
 * Admin Skill Review page (P2-4).
 *
 * Superuser-only queue for reviewing tenant-submitted skill candidates.
 * Approving publishes the snapshot to ``curated_skills``; rejecting records
 * a note and closes the submission.
 */

import { useState } from 'react';

import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();
  const [note, setNote] = useState('');
  const [bump, setBump] = useState<SemverBump | 'trust'>('trust');

  const mutation = useMutation({
    mutationFn: async () => {
      if (!submission) throw new Error(t('admin.skillReview.noSubmissionSelected'));
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
      message.success(
        mode === 'approve'
          ? t('admin.skillReview.approveSuccess')
          : t('admin.skillReview.rejectSuccess')
      );
      void qc.invalidateQueries({ queryKey: ['admin', 'skill-submissions'] });
      setNote('');
      setBump('trust');
      onClose();
    },
    onError: (err: Error) => {
      message.error(err.message || t('admin.skillReview.reviewFailed'));
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
      title={
        mode === 'approve'
          ? t('admin.skillReview.approveTitle')
          : t('admin.skillReview.rejectTitle')
      }
      open={open}
      onCancel={() => {
        setNote('');
        setBump('trust');
        onClose();
      }}
      onOk={() => {
        mutation.mutate();
      }}
      okText={
        mode === 'approve' ? t('admin.skillReview.approveOk') : t('admin.skillReview.rejectOk')
      }
      okButtonProps={{ danger: mode === 'reject', disabled: !submission }}
      confirmLoading={mutation.isPending}
    >
      <div className="space-y-4">
        <Text type="secondary">
          {mode === 'approve'
            ? t('admin.skillReview.approveDescription')
            : t('admin.skillReview.rejectDescription')}
        </Text>
        {mode === 'approve' ? (
          <div className={`space-y-2 rounded-[6px] p-3 ${surface}`}>
            <Text strong>{t('admin.skillReview.releaseVersion')}</Text>
            <Radio.Group
              value={bump}
              onChange={(e) => {
                setBump(e.target.value as SemverBump | 'trust');
              }}
            >
              <Radio value="trust">
                {t('admin.skillReview.trustSubmitter', {
                  version: submission?.proposed_semver ?? '-',
                })}
              </Radio>
              <Radio value="patch">{t('admin.skillReview.bumpPatch')}</Radio>
              <Radio value="minor">{t('admin.skillReview.bumpMinor')}</Radio>
              <Radio value="major">{t('admin.skillReview.bumpMajor')}</Radio>
            </Radio.Group>
            <Text type="secondary" className="text-xs">
              {t('admin.skillReview.effectiveVersion')}
              <Tag color="blue">v{effectiveSemver}</Tag>
              <span className="ml-2">{t('admin.skillReview.deprecateNote')}</span>
            </Text>
          </div>
        ) : null}
        <TextArea
          rows={4}
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
          placeholder={t('admin.skillReview.notePlaceholder')}
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
  const { t } = useTranslation();
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
          <div className={`mt-2 text-sm ${mutedText}`}>
            {t('admin.skillReview.submissionNotePrefix')}
            {submission.submission_note}
          </div>
        ) : null}
        {submission.review_note ? (
          <div
            className={
              submission.status === 'rejected'
                ? 'mt-2 text-sm text-[oklch(0.55_0.18_25)]'
                : `mt-2 text-sm ${mutedText}`
            }
          >
            {t('admin.skillReview.reviewNotePrefix')}
            {submission.review_note}
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
  const { t } = useTranslation();
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
        <Empty description={t('admin.skillReview.emptyDescription', { status })} />
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
  const { t } = useTranslation();
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      <div>
        <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>
          Admin Review
        </div>
        <Title level={3} className={`!mb-1 !mt-2 ${pageText}`}>
          {t('admin.skillReview.pageTitle')}
        </Title>
        <Paragraph type="secondary" className="!mb-0 max-w-3xl">
          {t('admin.skillReview.pageDescription')}
        </Paragraph>
      </div>
      <div className={`rounded-[6px] p-3 ${surface}`}>
        <Tabs
          defaultActiveKey="pending"
          items={[
            {
              key: 'pending',
              label: t('admin.skillReview.tabs.pending'),
              children: <SubmissionsList status="pending" />,
            },
            {
              key: 'approved',
              label: t('admin.skillReview.tabs.approved'),
              children: <SubmissionsList status="approved" />,
            },
            {
              key: 'rejected',
              label: t('admin.skillReview.tabs.rejected'),
              children: <SubmissionsList status="rejected" />,
            },
            {
              key: 'withdrawn',
              label: t('admin.skillReview.tabs.withdrawn'),
              children: <SubmissionsList status="withdrawn" />,
            },
          ]}
        />
      </div>
    </div>
  );
}
