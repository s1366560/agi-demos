import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Form, Input, Modal, Segmented, Switch, Tabs, Tag } from 'antd';

import {
  parseGeneConfig,
  parseRawConfigJson,
  serializeGeneConfig,
  validateGeneConfig,
  type GeneConfigDraft,
  type GeneConfigValidationError,
} from '@/types/geneConfig';

import { getCategoryColor } from './utils';

import { GeneConfigForm } from './GeneConfigForm';
import { GeneConfigJsonEditor } from './GeneConfigJsonEditor';

import type { CyberGene, CyberGeneCategory } from '@/types/workspace';

export interface GenePayload {
  name: string;
  category: CyberGeneCategory;
  description: string | null;
  config_json: string;
  version: string;
  is_active: boolean;
}

export interface GeneEditorModalProps {
  open: boolean;
  mode: 'create' | 'edit';
  initialGene?: CyberGene | null;
  /**
   * Optional pre-filled payload (e.g. when importing from the marketplace).
   * Used when `mode === 'create'` to seed the editor with marketplace data.
   */
  initialDraft?: Partial<GenePayload> | null;
  submitting?: boolean;
  onSubmit: (payload: GenePayload) => Promise<void> | void;
  onCancel: () => void;
}

const CATEGORIES: CyberGeneCategory[] = ['skill', 'knowledge', 'tool', 'workflow'];

const draftFromGene = (gene: CyberGene): GenePayload => ({
  name: gene.name,
  category: gene.category,
  description: gene.description ?? null,
  config_json: gene.config_json ?? '',
  version: gene.version,
  is_active: gene.is_active,
});

const draftFromPartial = (partial: Partial<GenePayload> | null | undefined): GenePayload => ({
  name: partial?.name ?? '',
  category: partial?.category ?? 'skill',
  description: partial?.description ?? null,
  config_json: partial?.config_json ?? '',
  version: partial?.version ?? '1.0.0',
  is_active: partial?.is_active ?? true,
});

export const GeneEditorModal: React.FC<GeneEditorModalProps> = ({
  open,
  mode,
  initialGene,
  initialDraft,
  submitting = false,
  onSubmit,
  onCancel,
}) => {
  const { t } = useTranslation();

  const [payload, setPayload] = useState<GenePayload>(() =>
    initialGene ? draftFromGene(initialGene) : draftFromPartial(initialDraft)
  );
  const [configDraft, setConfigDraft] = useState<GeneConfigDraft>(() =>
    parseGeneConfig(
      initialGene?.category ?? initialDraft?.category ?? 'skill',
      initialGene?.config_json ?? initialDraft?.config_json ?? null
    )
  );
  const [activeTab, setActiveTab] = useState<'structured' | 'json'>('structured');
  const [rawJson, setRawJson] = useState<string>('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [configErrors, setConfigErrors] = useState<GeneConfigValidationError[]>([]);
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Re-seed state when the modal opens with new initial data.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) return;
    const next = initialGene ? draftFromGene(initialGene) : draftFromPartial(initialDraft);
    setPayload(next);
    setConfigDraft(parseGeneConfig(next.category, next.config_json));
    setRawJson(next.config_json);
    setActiveTab('structured');
    setNameError(null);
    setConfigErrors([]);
    setJsonError(null);
  }, [open, initialGene, initialDraft]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const isCreate = mode === 'create';

  const handleCategoryChange = useCallback(
    (next: CyberGeneCategory) => {
      // Re-parse current json with the new schema (so previously-known fields
      // for the old category fall into `extra` and the new schema's fields get
      // their defaults).
      const reparsed = parseGeneConfig(next, payload.config_json);
      setPayload((p) => ({ ...p, category: next }));
      setConfigDraft(reparsed);
      setConfigErrors([]);
    },
    [payload.config_json]
  );

  const handleStructuredChange = useCallback(
    (nextDraft: GeneConfigDraft) => {
      setConfigDraft(nextDraft);
      const serialized = serializeGeneConfig(payload.category, nextDraft);
      setRawJson(serialized);
      setPayload((p) => ({ ...p, config_json: serialized }));
      setConfigErrors([]);
    },
    [payload.category]
  );

  const handleRawJsonChange = useCallback((next: string) => {
    setRawJson(next);
    setJsonError(null);
  }, []);

  // When switching from JSON back to structured, validate + sync draft.
  const handleTabChange = useCallback(
    (next: string) => {
      if (next === 'structured' && activeTab === 'json') {
        const parsed = parseRawConfigJson(rawJson);
        if (!parsed.ok) {
          setJsonError(parsed.error);
          return;
        }
        const serialized = JSON.stringify(parsed.value, null, 2);
        setRawJson(serialized);
        setConfigDraft(parseGeneConfig(payload.category, serialized));
        setPayload((p) => ({ ...p, config_json: serialized }));
      }
      if (next === 'json' && activeTab === 'structured') {
        // Make sure raw mirrors the latest structured state.
        const serialized = serializeGeneConfig(payload.category, configDraft);
        setRawJson(serialized);
        setPayload((p) => ({ ...p, config_json: serialized }));
      }
      setActiveTab(next as 'structured' | 'json');
    },
    [activeTab, configDraft, payload.category, rawJson]
  );

  const canSubmit = useMemo(
    () => payload.name.trim().length > 0 && !submitting,
    [payload.name, submitting]
  );

  const handleOk = useCallback(async () => {
    // Name check
    if (payload.name.trim() === '') {
      setNameError(t('workspaceDetail.genes.errors.nameRequired', 'Name is required'));
      return;
    }
    // Final JSON sync
    let configJson = payload.config_json;
    if (activeTab === 'json') {
      const parsed = parseRawConfigJson(rawJson);
      if (!parsed.ok) {
        setJsonError(parsed.error);
        return;
      }
      configJson = JSON.stringify(parsed.value, null, 2);
    } else {
      const errs = validateGeneConfig(payload.category, configDraft);
      if (errs.length > 0) {
        setConfigErrors(errs);
        return;
      }
      configJson = serializeGeneConfig(payload.category, configDraft);
    }
    await onSubmit({ ...payload, config_json: configJson });
  }, [activeTab, configDraft, onSubmit, payload, rawJson, t]);

  return (
    <Modal
      open={open}
      title={
        <div className="flex items-center gap-2">
          <span>
            {isCreate
              ? t('workspaceDetail.genes.createGene', 'Create Gene')
              : t('workspaceDetail.genes.editGene', 'Edit Gene')}
          </span>
          <Tag color={getCategoryColor(payload.category)} className="m-0 border-transparent">
            {payload.category}
          </Tag>
        </div>
      }
      width={720}
      onCancel={onCancel}
      onOk={() => {
        void handleOk();
      }}
      okButtonProps={{ disabled: !canSubmit, loading: submitting }}
      okText={
        isCreate
          ? t('workspaceDetail.genes.create', 'Create')
          : t('workspaceDetail.genes.save', 'Save')
      }
      destroyOnClose
    >
      <Form layout="vertical" className="space-y-3">
        <Form.Item
          label={t('workspaceDetail.genes.name', 'Name')}
          {...(nameError ? { validateStatus: 'error' as const, help: nameError } : {})}
          required
        >
          <Input
            value={payload.name}
            onChange={(e) => {
              setPayload((p) => ({ ...p, name: e.target.value }));
              if (nameError) setNameError(null);
            }}
          />
        </Form.Item>

        <Form.Item label={t('workspaceDetail.genes.categoryLabel', 'Category')}>
          <Segmented
            options={CATEGORIES.map((c) => ({
              label: t(`workspaceDetail.genes.${c}`, c.charAt(0).toUpperCase() + c.slice(1)),
              value: c,
            }))}
            value={payload.category}
            onChange={(v) => {
              handleCategoryChange(v as CyberGeneCategory);
            }}
          />
        </Form.Item>

        <Form.Item label={t('workspaceDetail.genes.description', 'Description')}>
          <Input.TextArea
            value={payload.description ?? ''}
            autoSize={{ minRows: 2, maxRows: 4 }}
            onChange={(e) => {
              setPayload((p) => ({ ...p, description: e.target.value }));
            }}
          />
        </Form.Item>

        <div className="grid grid-cols-2 gap-3">
          <Form.Item label={t('workspaceDetail.genes.version', 'Version')}>
            <Input
              value={payload.version}
              onChange={(e) => {
                setPayload((p) => ({ ...p, version: e.target.value }));
              }}
            />
          </Form.Item>
          <Form.Item label={t('workspaceDetail.genes.active', 'Active')}>
            <Switch
              checked={payload.is_active}
              onChange={(next) => {
                setPayload((p) => ({ ...p, is_active: next }));
              }}
            />
          </Form.Item>
        </div>

        <Form.Item label={t('workspaceDetail.genes.config.title', 'Configuration')}>
          <Tabs
            activeKey={activeTab}
            onChange={handleTabChange}
            items={[
              {
                key: 'structured',
                label: t('workspaceDetail.genes.config.structured', 'Structured'),
                children: (
                  <GeneConfigForm
                    category={payload.category}
                    draft={configDraft}
                    errors={configErrors}
                    onChange={handleStructuredChange}
                  />
                ),
              },
              {
                key: 'json',
                label: t('workspaceDetail.genes.config.json', 'JSON'),
                children: (
                  <div className="space-y-2">
                    <GeneConfigJsonEditor value={rawJson} onChange={handleRawJsonChange} />
                    {jsonError && (
                      <div className="text-xs text-red-500">
                        {t('workspaceDetail.genes.config.invalidJson', 'Invalid JSON')}: {jsonError}
                      </div>
                    )}
                  </div>
                ),
              },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
};
