/**
 * Submit a private skill to the curated review queue (P2-4).
 *
 * Modal with semver + optional note. Submitting writes a row to
 * ``skill_submissions`` with status=pending; admins review it on the
 * dedicated admin page.
 */

import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { useMutation } from '@tanstack/react-query';
import { Input, Modal, Space, Typography, message } from 'antd';

import { curatedSkillAPI } from '@/services/curatedSkillService';

import type { SkillResponse } from '@/types/agent';

const { Text } = Typography;
const { TextArea } = Input;

const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';

interface SubmitSkillDialogProps {
  skill: SkillResponse | null;
  open: boolean;
  onClose: () => void;
}

const SEMVER_PATTERN = /^\d+\.\d+\.\d+$/;

export function SubmitSkillDialog({ skill, open, onClose }: SubmitSkillDialogProps) {
  const { t } = useTranslation();
  const [semver, setSemver] = useState('0.1.0');
  const [note, setNote] = useState('');

  useEffect(() => {
    if (!open) {
      return;
    }

    const resetTimer = window.setTimeout(() => {
      setSemver('0.1.0');
      setNote('');
    }, 0);

    return () => {
      window.clearTimeout(resetTimer);
    };
  }, [open]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!skill) throw new Error(t('skill.submit.noSkillSelected'));
      return curatedSkillAPI.submit(skill.id, {
        proposed_semver: semver,
        submission_note: note || null,
      });
    },
    onSuccess: () => {
      message.success(t('skill.submit.successMessage'));
      onClose();
    },
    onError: (err: Error) => {
      message.error(err.message || t('skill.submit.failedMessage'));
    },
  });

  const invalidSemver = !SEMVER_PATTERN.test(semver);

  return (
    <Modal
      title={
        skill
          ? t('skill.submit.titleWithName', { name: skill.name })
          : t('skill.submit.titleGeneric')
      }
      open={open}
      onCancel={onClose}
      onOk={() => {
        mutation.mutate();
      }}
      okText={t('skill.submit.okText')}
      okButtonProps={{ disabled: invalidSemver || !skill }}
      confirmLoading={mutation.isPending}
    >
      <Space orientation="vertical" className="w-full" size="middle">
        <div className={`rounded-[6px] p-3 ${surface}`}>
          <Text type="secondary">{t('skill.submit.description')}</Text>
        </div>
        <div>
          <label htmlFor="skill-submit-semver" className="font-medium">
            {t('skill.submit.versionLabel')}
          </label>
          <Input
            id="skill-submit-semver"
            className="mt-2"
            value={semver}
            onChange={(e) => {
              setSemver(e.target.value);
            }}
            placeholder="0.1.0"
            status={invalidSemver ? 'error' : ''}
          />
          {invalidSemver ? (
            <Text type="danger" className="text-xs">
              {t('skill.submit.versionFormatHint')}
            </Text>
          ) : null}
        </div>
        <div>
          <label htmlFor="skill-submit-note" className="font-medium">
            {t('skill.submit.noteLabel')}
          </label>
          <TextArea
            id="skill-submit-note"
            className="mt-2"
            rows={4}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
            placeholder={t('skill.submit.notePlaceholder')}
            maxLength={2000}
            showCount
          />
        </div>
      </Space>
    </Modal>
  );
}

export default SubmitSkillDialog;
