/**
 * Skill detail page.
 *
 * Shows the Agent Skills package metadata, content, lineage, and version history.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC, ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { Alert, Tag } from 'antd';
import {
  ArrowLeft,
  ArrowUpCircle,
  Download,
  FileText,
  History,
  KeyRound,
  Pencil,
  RefreshCw,
  RotateCcw,
  Wrench,
} from 'lucide-react';

import { skillAPI } from '@/services/skillService';

import { SkillModal } from '@/components/skill/SkillModal';
import { LazyEmpty, LazyPopconfirm, LazySpin, useLazyMessage } from '@/components/ui/lazyAntd';

import type { SkillResponse, SkillVersionResponse } from '@/types/agent';

type SkillSource = NonNullable<SkillResponse['source']>;

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';
const actionButton =
  'inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] disabled:cursor-not-allowed disabled:opacity-60 dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]';

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : '';
}

function jsonBlock(value: Record<string, unknown> | undefined): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid gap-1 border-b border-[oklch(0.9_0.006_255)] py-3 last:border-b-0 dark:border-[oklch(0.28_0.006_255)] sm:grid-cols-[140px_minmax(0,1fr)]">
      <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>{label}</div>
      <div
        className={`min-w-0 break-words text-sm ${pageText} ${
          mono ? 'font-mono text-xs leading-5' : ''
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function getSkillSource(skill: SkillResponse): SkillSource {
  return skill.source ?? 'database';
}

function isManagedSkill(skill: SkillResponse): boolean {
  const source = getSkillSource(skill);
  return !skill.is_system_skill && (source === 'database' || source === 'hybrid');
}

export const SkillDetail: FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ skillId: string }>();
  const message = useLazyMessage();
  const skillId = params.skillId;

  const [skill, setSkill] = useState<SkillResponse | null>(null);
  const [versions, setVersions] = useState<SkillVersionResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [rollbackVersion, setRollbackVersion] = useState<number | null>(null);
  const [isUpgrading, setIsUpgrading] = useState(false);

  const metadataText = useMemo(() => jsonBlock(skill?.metadata), [skill?.metadata]);
  const allowedToolsRaw = skill?.allowed_tools_raw ?? skill?.tools.join(' ') ?? '';
  const skillScope = skill ? t(`tenant.skills.detail.scopeValues.${skill.scope}`) : '';
  const skillSource = skill ? getSkillSource(skill) : 'database';
  const managed = skill ? isManagedSkill(skill) : false;

  const loadSkill = useCallback(async () => {
    if (!skillId) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      const nextSkill = await skillAPI.get(skillId);
      setSkill(nextSkill);
      if (!isManagedSkill(nextSkill)) {
        setVersions([]);
      } else {
        try {
          const versionResult = await skillAPI.listVersions(nextSkill.id);
          setVersions(versionResult.versions);
        } catch {
          setVersions([]);
          message?.error(t('tenant.skills.detail.versionLoadFailed'));
        }
      }
    } catch {
      setSkill(null);
      message?.error(t('tenant.skills.detail.loadFailed'));
    } finally {
      setIsLoading(false);
    }
  }, [message, skillId, t]);

  useEffect(() => {
    void loadSkill();
  }, [loadSkill]);

  const handleExport = useCallback(async () => {
    if (!skill) {
      return;
    }
    try {
      const exportId = getSkillSource(skill) === 'filesystem' ? skill.name : skill.id;
      const exported = await skillAPI.exportPackage(exportId);
      const blob = new Blob([JSON.stringify(exported, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${skill.name}.agentskill.json`;
      link.click();
      URL.revokeObjectURL(url);
      message?.success(t('tenant.skills.detail.exportSuccess'));
    } catch {
      message?.error(t('tenant.skills.detail.exportFailed'));
    }
  }, [message, skill, t]);

  const handleUpgrade = useCallback(async () => {
    if (!skill) {
      return;
    }
    if (!isManagedSkill(skill)) {
      message?.info(t('tenant.skills.detail.readOnlySource'));
      return;
    }
    setIsUpgrading(true);
    try {
      const result = await skillAPI.upgrade(skill.id);
      if (result.action === 'noop') {
        message?.info(t('tenant.skills.detail.upgradeNoop'));
      } else {
        message?.success(t('tenant.skills.detail.upgradeSuccess'));
        await loadSkill();
      }
    } catch {
      message?.error(t('tenant.skills.detail.upgradeFailed'));
    } finally {
      setIsUpgrading(false);
    }
  }, [loadSkill, message, skill, t]);

  const handleRollback = useCallback(
    async (versionNumber: number) => {
      if (!skill) {
        return;
      }
      if (!isManagedSkill(skill)) {
        message?.info(t('tenant.skills.detail.readOnlySource'));
        return;
      }
      setRollbackVersion(versionNumber);
      try {
        await skillAPI.rollback(skill.id, versionNumber);
        message?.success(t('tenant.skills.detail.rollbackSuccess'));
        await loadSkill();
      } catch {
        message?.error(t('tenant.skills.detail.rollbackFailed'));
      } finally {
        setRollbackVersion(null);
      }
    },
    [loadSkill, message, skill, t]
  );

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    void loadSkill();
  }, [loadSkill]);

  if (isLoading) {
    return (
      <div
        className={`mx-auto flex w-full max-w-7xl justify-center rounded-[6px] py-16 ${surface}`}
      >
        <LazySpin size="large" />
      </div>
    );
  }

  if (!skill) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
        <button
          type="button"
          onClick={() => {
            void navigate('..');
          }}
          className={actionButton}
        >
          <ArrowLeft size={16} />
          {t('tenant.skills.detail.back')}
        </button>
        <Alert type="warning" title={t('tenant.skills.detail.notFound')} showIcon />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            onClick={() => {
              void navigate('..');
            }}
            className={`mb-3 inline-flex h-8 items-center gap-2 text-sm font-medium ${mutedText} hover:text-[oklch(0.24_0.01_255)] dark:hover:text-[oklch(0.94_0.006_255)]`}
          >
            <ArrowLeft size={16} />
            {t('tenant.skills.detail.back')}
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className={`truncate text-2xl font-semibold leading-8 tracking-normal ${pageText}`}>
              {skill.name}
            </h1>
            <Tag color={skill.status === 'active' ? 'success' : 'default'}>
              {t(`common.status.${skill.status}`)}
            </Tag>
            <Tag>{skillScope}</Tag>
            <Tag>{t(`tenant.skills.source.${skillSource}`)}</Tag>
            {(skill.semver ?? skill.version_label) ? (
              <Tag>{skill.semver ?? skill.version_label}</Tag>
            ) : null}
          </div>
          <p className={`mt-2 max-w-3xl text-sm ${mutedText}`}>{skill.description}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              void loadSkill();
            }}
            className={actionButton}
          >
            <RefreshCw size={16} />
            {t('tenant.skills.detail.refresh')}
          </button>
          <button
            type="button"
            onClick={() => {
              setIsModalOpen(true);
            }}
            className={actionButton}
            disabled={!managed}
          >
            <Pencil size={16} />
            {t('tenant.skills.detail.edit')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleExport();
            }}
            className={actionButton}
          >
            <Download size={16} />
            {t('tenant.skills.detail.export')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleUpgrade();
            }}
            className={actionButton}
            disabled={isUpgrading || !managed}
          >
            <ArrowUpCircle size={16} />
            {isUpgrading ? t('tenant.skills.detail.upgrading') : t('tenant.skills.detail.upgrade')}
          </button>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-5">
          <section className={`rounded-[6px] p-5 ${surface}`}>
            <div className="flex items-center gap-2">
              <Wrench size={17} className={mutedText} />
              <h2 className={`text-sm font-semibold ${pageText}`}>
                {t('tenant.skills.detail.package')}
              </h2>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {skill.tools.map((tool) => (
                <Tag key={tool}>{tool}</Tag>
              ))}
            </div>
            <div className="mt-4">
              <InfoRow
                label={t('tenant.skills.detail.allowedToolsRaw')}
                value={allowedToolsRaw || t('tenant.skills.detail.notSet')}
              />
              <InfoRow
                label={t('tenant.skills.detail.license')}
                value={skill.license || t('tenant.skills.detail.notSet')}
              />
              <InfoRow
                label={t('tenant.skills.detail.compatibility')}
                value={skill.compatibility || t('tenant.skills.detail.notSet')}
              />
              <InfoRow label={t('tenant.skills.detail.specVersion')} value={skill.spec_version} />
            </div>
          </section>

          <section className={`rounded-[6px] p-5 ${surface}`}>
            <div className="flex items-center gap-2">
              <FileText size={17} className={mutedText} />
              <h2 className={`text-sm font-semibold ${pageText}`}>
                {t('tenant.skills.detail.fullContent')}
              </h2>
            </div>
            {skill.full_content ? (
              <pre className="mt-4 max-h-[520px] overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] p-4 text-xs leading-5 text-[oklch(0.24_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)] dark:text-[oklch(0.88_0.006_255)]">
                {skill.full_content}
              </pre>
            ) : (
              <div className="mt-4 py-8">
                <LazyEmpty description={t('tenant.skills.detail.emptyContent')} />
              </div>
            )}
          </section>

          <section className={`rounded-[6px] p-5 ${surface}`}>
            <div className="flex items-center gap-2">
              <KeyRound size={17} className={mutedText} />
              <h2 className={`text-sm font-semibold ${pageText}`}>
                {t('tenant.skills.detail.metadata')}
              </h2>
            </div>
            <pre className="mt-4 max-h-[360px] overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] p-4 text-xs leading-5 text-[oklch(0.24_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)] dark:text-[oklch(0.88_0.006_255)]">
              {metadataText}
            </pre>
          </section>
        </div>

        <aside className="flex min-w-0 flex-col gap-5">
          <section className={`rounded-[6px] p-5 ${surface}`}>
            <h2 className={`text-sm font-semibold ${pageText}`}>
              {t('tenant.skills.detail.identity')}
            </h2>
            <div className="mt-3">
              <InfoRow label={t('tenant.skills.detail.id')} value={skill.id} mono />
              <InfoRow
                label={t('tenant.skills.detail.source')}
                value={t(`tenant.skills.source.${skillSource}`)}
              />
              <InfoRow
                label={t('tenant.skills.detail.filePath')}
                value={skill.file_path || t('tenant.skills.detail.notSet')}
                mono={Boolean(skill.file_path)}
              />
              <InfoRow label={t('tenant.skills.detail.scope')} value={skillScope} />
              <InfoRow
                label={t('tenant.skills.detail.project')}
                value={skill.project_id || t('tenant.skills.detail.notSet')}
                mono={Boolean(skill.project_id)}
              />
              <InfoRow
                label={t('tenant.skills.detail.created')}
                value={formatDate(skill.created_at)}
              />
              <InfoRow
                label={t('tenant.skills.detail.updated')}
                value={formatDate(skill.updated_at)}
              />
            </div>
          </section>

          <section className={`rounded-[6px] p-5 ${surface}`}>
            <h2 className={`text-sm font-semibold ${pageText}`}>
              {t('tenant.skills.detail.lineage')}
            </h2>
            <div className="mt-3">
              <InfoRow
                label={t('tenant.skills.detail.parentCurated')}
                value={skill.parent_curated_id || t('tenant.skills.detail.notSet')}
                mono={Boolean(skill.parent_curated_id)}
              />
              <InfoRow
                label={t('tenant.skills.detail.semver')}
                value={skill.semver || t('tenant.skills.detail.notSet')}
              />
              <InfoRow
                label={t('tenant.skills.detail.revisionHash')}
                value={skill.revision_hash || t('tenant.skills.detail.notSet')}
                mono={Boolean(skill.revision_hash)}
              />
            </div>
          </section>

          <section className={`rounded-[6px] p-5 ${surface}`}>
            <div className="flex items-center gap-2">
              <History size={17} className={mutedText} />
              <h2 className={`text-sm font-semibold ${pageText}`}>
                {t('tenant.skills.detail.versions')}
              </h2>
            </div>
            {versions.length === 0 ? (
              <div className="py-8">
                <LazyEmpty
                  description={
                    managed
                      ? t('tenant.skills.detail.emptyVersions')
                      : t('tenant.skills.detail.notVersioned')
                  }
                />
              </div>
            ) : (
              <div className="mt-3 divide-y divide-[oklch(0.9_0.006_255)] dark:divide-[oklch(0.28_0.006_255)]">
                {versions.map((version) => {
                  const isCurrent = skill.current_version === version.version_number;
                  return (
                    <div key={version.id} className="py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`text-sm font-semibold ${pageText}`}>
                              {version.version_label ?? `#${String(version.version_number)}`}
                            </span>
                            <span className={`text-xs ${mutedText}`}>
                              #{version.version_number}
                            </span>
                            {isCurrent ? (
                              <Tag color="success">{t('tenant.skills.detail.current')}</Tag>
                            ) : null}
                          </div>
                          {version.change_summary ? (
                            <div className={`mt-1 text-sm ${mutedText}`}>
                              {version.change_summary}
                            </div>
                          ) : null}
                          <div className={`mt-1 text-xs ${mutedText}`}>
                            {t('tenant.skills.detail.versionCreatedBy', {
                              author: version.created_by,
                              date: formatDate(version.created_at),
                            })}
                          </div>
                        </div>
                        {!isCurrent ? (
                          <LazyPopconfirm
                            title={t('tenant.skills.detail.rollbackConfirm')}
                            okText={t('common.confirm')}
                            cancelText={t('common.cancel')}
                            onConfirm={() => {
                              void handleRollback(version.version_number);
                            }}
                          >
                            <button
                              type="button"
                              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[4px] text-[oklch(0.48_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] hover:text-[oklch(0.26_0.012_255)] disabled:cursor-not-allowed disabled:opacity-60 dark:text-[oklch(0.7_0.008_255)] dark:hover:bg-[oklch(0.24_0.006_255)]"
                              title={t('tenant.skills.detail.rollback')}
                              aria-label={t('tenant.skills.detail.rollback')}
                              disabled={rollbackVersion !== null}
                            >
                              <RotateCcw size={15} />
                            </button>
                          </LazyPopconfirm>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </aside>
      </div>

      {isModalOpen ? (
        <SkillModal
          isOpen={isModalOpen}
          skill={skill}
          onClose={() => {
            setIsModalOpen(false);
          }}
          onSuccess={handleModalSuccess}
        />
      ) : null}
    </div>
  );
};

export default SkillDetail;
