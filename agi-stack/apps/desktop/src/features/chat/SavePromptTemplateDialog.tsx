import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Dialog, Select, TextArea, TextField } from '@radix-ui/themes';
import { Cross2Icon, FileTextIcon } from '@radix-ui/react-icons';

import { DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import type { PromptTemplateRecord } from '../../types';
import type { ComposerCatalogClient } from './composerCatalogModel';
import {
  promptTemplatePreview,
  promptTemplateRequestMatches,
  promptTemplateSaveErrorKey,
  validatePromptTemplateDraft,
} from './promptTemplateModel';
import type { PromptTemplateCategory } from './promptTemplateModel';

export type SavePromptTemplateTarget = {
  messageId: string;
  tenantId: string;
  projectId: string;
  conversationId: string;
  content: string;
  returnFocus: HTMLElement | null;
};

export function SavePromptTemplateDialog({
  api,
  target,
  onClose,
  onSaved,
}: {
  api: ComposerCatalogClient;
  target: SavePromptTemplateTarget;
  onClose: () => void;
  onSaved: (template: PromptTemplateRecord) => void;
}) {
  const { t } = useI18n();
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState<PromptTemplateCategory>('general');
  const [titleError, setTitleError] = useState<string | null>(null);
  const [saveErrorKey, setSaveErrorKey] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const saveRequestRef = useRef<AbortController | null>(null);
  const requestGenerationRef = useRef(0);
  const saveLockRef = useRef(false);
  const scopeKey = `${target.tenantId}:${target.projectId}:${target.conversationId}:${target.messageId}`;
  const currentScopeKeyRef = useRef(scopeKey);
  currentScopeKeyRef.current = scopeKey;

  const close = useCallback(() => {
    saveRequestRef.current?.abort();
    saveRequestRef.current = null;
    requestGenerationRef.current += 1;
    saveLockRef.current = false;
    onClose();
  }, [onClose]);

  useEffect(
    () => () => {
      saveRequestRef.current?.abort();
      requestGenerationRef.current += 1;
      saveLockRef.current = false;
    },
    [],
  );

  const submit = useCallback(async () => {
    if (saveLockRef.current) return;
    const validation = validatePromptTemplateDraft({
      title,
      content: target.content,
      category,
    });
    if (!validation.ok) {
      if (validation.errorKey === 'chat.templates.saveTitleRequired') {
        setTitleError(validation.errorKey);
      } else {
        setSaveErrorKey(validation.errorKey);
      }
      return;
    }
    if (!api.createPromptTemplate) {
      setSaveErrorKey('chat.templates.unavailable');
      return;
    }

    const controller = new AbortController();
    saveRequestRef.current?.abort();
    saveRequestRef.current = controller;
    const requestId = ++requestGenerationRef.current;
    const expectedScopeKey = scopeKey;
    saveLockRef.current = true;
    setSaving(true);
    setSaveErrorKey(null);
    try {
      const created = await api.createPromptTemplate(
        target.tenantId,
        validation.value,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        !promptTemplateRequestMatches({
          requestId,
          currentRequestId: requestGenerationRef.current,
          expectedScopeKey,
          currentScopeKey: currentScopeKeyRef.current,
        })
      ) {
        return;
      }
      saveRequestRef.current = null;
      saveLockRef.current = false;
      onSaved(created);
      onClose();
    } catch (error) {
      if (
        controller.signal.aborted ||
        !promptTemplateRequestMatches({
          requestId,
          currentRequestId: requestGenerationRef.current,
          expectedScopeKey,
          currentScopeKey: currentScopeKeyRef.current,
        })
      ) {
        return;
      }
      saveRequestRef.current = null;
      saveLockRef.current = false;
      setSaving(false);
      setSaveErrorKey(
        promptTemplateSaveErrorKey(error instanceof DesktopApiError ? error.status : undefined),
      );
    }
  }, [api, category, onClose, onSaved, scopeKey, target.content, target.tenantId, title]);

  const nameId = `save-prompt-template-name-${target.messageId}`;
  const categoryId = `save-prompt-template-category-${target.messageId}`;
  const previewId = `save-prompt-template-preview-${target.messageId}`;

  return (
    <Dialog.Root open onOpenChange={(nextOpen) => !nextOpen && close()}>
      <Dialog.Content
        className="save-prompt-template-dialog"
        maxWidth="520px"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          target.returnFocus?.focus();
        }}
      >
        <div className="prompt-template-heading">
          <span>
            <Dialog.Title>{t('chat.templates.saveAsTemplate')}</Dialog.Title>
            <Dialog.Description>{t('chat.templates.saveDescription')}</Dialog.Description>
          </span>
          <Dialog.Close>
            <Button type="button" variant="ghost" color="gray" aria-label={t('common.close')}>
              <Cross2Icon aria-hidden="true" />
            </Button>
          </Dialog.Close>
        </div>

        <form
          className="save-prompt-template-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label htmlFor={nameId}>
            <span>{t('chat.templates.saveName')}</span>
            <TextField.Root
              id={nameId}
              autoFocus
              value={title}
              maxLength={200}
              aria-invalid={Boolean(titleError)}
              aria-describedby={titleError ? `${nameId}-error` : undefined}
              placeholder={t('chat.templates.saveNamePlaceholder')}
              onChange={(event) => {
                const nextTitle = event.currentTarget.value;
                setTitle(nextTitle);
                setTitleError(null);
                setSaveErrorKey(null);
              }}
            />
          </label>
          {titleError ? (
            <small id={`${nameId}-error`} className="prompt-template-field-error" role="alert">
              {t(titleError)}
            </small>
          ) : null}

          <label htmlFor={categoryId}>
            <span>{t('chat.templates.saveCategory')}</span>
            <Select.Root
              value={category}
              onValueChange={(value) => {
                setCategory(value as PromptTemplateCategory);
                setSaveErrorKey(null);
              }}
              disabled={saving}
            >
              <Select.Trigger id={categoryId} aria-label={t('chat.templates.saveCategory')} />
              <Select.Content>
                {(['general', 'analysis', 'code', 'writing'] as const).map((value) => (
                  <Select.Item value={value} key={value}>
                    {t(`chat.templates.category.${value}`)}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </label>

          <label htmlFor={previewId}>
            <span>{t('chat.templates.preview')}</span>
            <TextArea
              id={previewId}
              value={promptTemplatePreview(target.content)}
              readOnly
              resize="vertical"
              rows={6}
            />
          </label>

          {saveErrorKey ? (
            <div className="prompt-template-error" role="alert">
              {t(saveErrorKey)}
            </div>
          ) : null}
          <span className="sr-only" aria-live="polite">
            {saving ? t('chat.templates.saving') : ''}
          </span>

          <div className="prompt-template-dialog-actions">
            <Dialog.Close>
              <Button type="button" variant="soft" color="gray">
                {t('common.cancel')}
              </Button>
            </Dialog.Close>
            <Button type="submit" disabled={saving}>
              <FileTextIcon aria-hidden="true" />
              {saving ? t('chat.templates.saving') : t('common.save')}
            </Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Root>
  );
}
