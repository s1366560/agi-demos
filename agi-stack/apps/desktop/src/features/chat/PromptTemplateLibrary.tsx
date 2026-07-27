import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertDialog, Button, Dialog, TextArea, TextField } from '@radix-ui/themes';
import {
  Cross2Icon,
  FileTextIcon,
  MagnifyingGlassIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { DesktopApiError } from '../../api/client';
import { useI18n } from '../../i18n';
import type { PromptTemplateRecord } from '../../types';
import type { ComposerCatalogClient } from './composerCatalogModel';
import {
  BUILTIN_PROMPT_TEMPLATES,
  filterPromptTemplates,
  promptTemplateErrorKey,
  promptTemplateRequestMatches,
  promptTemplateVariableFields,
  resolvePromptTemplate,
} from './promptTemplateModel';
import type {
  PromptTemplateCategoryFilter,
  PromptTemplateListItem,
  PromptTemplateSource,
} from './promptTemplateModel';

type PromptTemplateLibraryProps = {
  api: ComposerCatalogClient;
  tenantId: string;
  projectId: string;
  conversationId: string;
  refreshToken?: number;
  disabled?: boolean;
  onInsert: (prompt: string) => void;
};

type CatalogStatus = 'idle' | 'loading' | 'ready' | 'error';

type ScopedTemplateSelection = {
  template: PromptTemplateListItem;
  selectionScopeKey: string;
};

const CATEGORIES: readonly PromptTemplateCategoryFilter[] = [
  'all',
  'analysis',
  'code',
  'writing',
  'general',
];

export function PromptTemplateLibrary({
  api,
  tenantId,
  projectId,
  conversationId,
  refreshToken = 0,
  disabled = false,
  onInsert,
}: PromptTemplateLibraryProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<PromptTemplateSource>('builtin');
  const [category, setCategory] = useState<PromptTemplateCategoryFilter>('all');
  const [query, setQuery] = useState('');
  const [customTemplates, setCustomTemplates] = useState<PromptTemplateRecord[]>([]);
  const [catalogStatus, setCatalogStatus] = useState<CatalogStatus>('idle');
  const [catalogErrorKey, setCatalogErrorKey] = useState<string | null>(null);
  const [retryRevision, setRetryRevision] = useState(0);
  const [variableSelection, setVariableSelection] = useState<ScopedTemplateSelection | null>(null);
  const [variableValues, setVariableValues] = useState<Record<string, string>>({});
  const [missingVariables, setMissingVariables] = useState<ReadonlySet<string>>(new Set());
  const [deleteSelection, setDeleteSelection] = useState<ScopedTemplateSelection | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRequestRef = useRef<AbortController | null>(null);
  const deleteRequestRef = useRef<AbortController | null>(null);
  const requestGenerationRef = useRef(0);
  const scopeKey = `${tenantId}:${projectId}:${conversationId}`;
  const currentScopeKeyRef = useRef(scopeKey);
  currentScopeKeyRef.current = scopeKey;
  const scopeReady = Boolean(tenantId.trim() && projectId.trim() && conversationId.trim());

  const builtinTemplates = useMemo<PromptTemplateListItem[]>(
    () =>
      BUILTIN_PROMPT_TEMPLATES.map((template) => ({
        key: `builtin:${template.id}`,
        id: template.id,
        source: 'builtin',
        title: translatedOrFallback(
          t(template.titleKey),
          template.titleKey,
          template.titleFallback,
        ),
        content: translatedOrFallback(
          t(template.contentKey),
          template.contentKey,
          template.contentFallback,
        ),
        category: template.category,
        variables: [],
        canDelete: false,
      })),
    [t],
  );

  const customListItems = useMemo<PromptTemplateListItem[]>(
    () =>
      customTemplates.map((template) => ({
        key: `custom:${template.id}`,
        id: template.id,
        source: 'custom',
        title: template.title,
        content: template.content,
        category: normalizeCategory(template.category),
        variables: template.variables,
        canDelete: !template.is_system,
      })),
    [customTemplates],
  );

  const visibleTemplates = useMemo(
    () =>
      filterPromptTemplates([...builtinTemplates, ...customListItems], {
        source,
        category,
        query,
      }),
    [builtinTemplates, category, customListItems, query, source],
  );

  useEffect(() => {
    listRequestRef.current?.abort();
    deleteRequestRef.current?.abort();
    requestGenerationRef.current += 1;
    setOpen(false);
    setVariableSelection(null);
    setDeleteSelection(null);
    setDeleteBusy(false);
    setMissingVariables(new Set());
    setCatalogErrorKey(null);
    setCatalogStatus('idle');
    setCustomTemplates([]);
  }, [scopeKey]);

  useEffect(() => {
    if (!open || !scopeReady) return;
    if (!api.listPromptTemplates) {
      setCatalogStatus('error');
      setCatalogErrorKey('chat.templates.unavailable');
      return;
    }
    const controller = new AbortController();
    listRequestRef.current?.abort();
    listRequestRef.current = controller;
    const requestId = ++requestGenerationRef.current;
    const expectedScopeKey = scopeKey;
    setCatalogStatus('loading');
    setCatalogErrorKey(null);
    void api
      .listPromptTemplates(tenantId, controller.signal)
      .then((templates) => {
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
        listRequestRef.current = null;
        setCustomTemplates(templates);
        setCatalogStatus('ready');
      })
      .catch((error) => {
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
        listRequestRef.current = null;
        setCatalogStatus('error');
        setCatalogErrorKey(
          promptTemplateErrorKey(error instanceof DesktopApiError ? error.status : undefined),
        );
      });
    return () => {
      controller.abort();
      if (listRequestRef.current === controller) listRequestRef.current = null;
    };
  }, [api, open, refreshToken, retryRevision, scopeKey, scopeReady, tenantId]);

  useEffect(
    () => () => {
      listRequestRef.current?.abort();
      deleteRequestRef.current?.abort();
    },
    [],
  );

  const resetFilters = useCallback(() => {
    setCategory('all');
    setQuery('');
  }, []);

  const closeLibrary = useCallback(() => {
    listRequestRef.current?.abort();
    requestGenerationRef.current += 1;
    setOpen(false);
    setSource('builtin');
    resetFilters();
  }, [resetFilters]);

  const insertTemplate = useCallback(
    (selection: ScopedTemplateSelection, content: string) => {
      if (selection.selectionScopeKey !== currentScopeKeyRef.current) return;
      onInsert(content);
      setVariableSelection(null);
      setVariableValues({});
      setMissingVariables(new Set());
      closeLibrary();
    },
    [closeLibrary, onInsert],
  );

  const chooseTemplate = useCallback(
    (template: PromptTemplateListItem) => {
      const selection = { template, selectionScopeKey: scopeKey };
      const variables = promptTemplateVariableFields(template.content, template.variables);
      if (!variables.length) {
        insertTemplate(selection, template.content);
        return;
      }
      setVariableValues(
        Object.fromEntries(variables.map((variable) => [variable.name, variable.default_value])),
      );
      setMissingVariables(new Set());
      setVariableSelection(selection);
      setOpen(false);
    },
    [insertTemplate, scopeKey],
  );

  const variableFields = useMemo(
    () =>
      variableSelection
        ? promptTemplateVariableFields(
            variableSelection.template.content,
            variableSelection.template.variables,
          )
        : [],
    [variableSelection],
  );

  const variablePreview = useMemo(() => {
    if (!variableSelection) return '';
    return (
      resolvePromptTemplate(variableSelection.template.content, variableFields, variableValues)
        .content ?? variableSelection.template.content
    );
  }, [variableFields, variableSelection, variableValues]);

  const submitVariables = useCallback(() => {
    if (!variableSelection) return;
    const resolved = resolvePromptTemplate(
      variableSelection.template.content,
      variableFields,
      variableValues,
    );
    if (resolved.missingRequired.length) {
      setMissingVariables(new Set(resolved.missingRequired));
      return;
    }
    if (resolved.content !== null) insertTemplate(variableSelection, resolved.content);
  }, [insertTemplate, variableFields, variableSelection, variableValues]);

  const confirmDelete = useCallback(async () => {
    if (!deleteSelection || !api.deletePromptTemplate || deleteBusy) return;
    if (deleteSelection.selectionScopeKey !== currentScopeKeyRef.current) {
      setDeleteSelection(null);
      return;
    }
    const controller = new AbortController();
    deleteRequestRef.current?.abort();
    deleteRequestRef.current = controller;
    const requestId = ++requestGenerationRef.current;
    const expectedScopeKey = deleteSelection.selectionScopeKey;
    const templateId = deleteSelection.template.id;
    setDeleteBusy(true);
    setCatalogErrorKey(null);
    try {
      await api.deletePromptTemplate(templateId, controller.signal);
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
      deleteRequestRef.current = null;
      setCustomTemplates((current) => current.filter((template) => template.id !== templateId));
      setDeleteSelection(null);
      setDeleteBusy(false);
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
      deleteRequestRef.current = null;
      setDeleteBusy(false);
      setCatalogErrorKey(
        promptTemplateErrorKey(error instanceof DesktopApiError ? error.status : undefined),
      );
      setDeleteSelection(null);
    }
  }, [api, deleteBusy, deleteSelection]);

  const sourceCount = source === 'builtin' ? builtinTemplates.length : customListItems.length;

  return (
    <div className="prompt-template-library">
      <Button
        type="button"
        size="1"
        variant="ghost"
        color="gray"
        disabled={disabled || !scopeReady}
        aria-label={t('chat.templates.open')}
        title={t('chat.templates.open')}
        onClick={() => {
          setOpen(true);
          window.requestAnimationFrame(() => searchRef.current?.focus());
        }}
      >
        <FileTextIcon aria-hidden="true" />
        <span>{t('chat.templates.trigger')}</span>
      </Button>

      <Dialog.Root
        open={open}
        onOpenChange={(nextOpen) => (nextOpen ? setOpen(true) : closeLibrary())}
      >
        <Dialog.Content className="prompt-template-dialog" maxWidth="780px">
          <div className="prompt-template-heading">
            <span>
              <Dialog.Title>{t('chat.templates.title')}</Dialog.Title>
              <Dialog.Description>{t('chat.templates.description')}</Dialog.Description>
            </span>
            <Dialog.Close>
              <Button type="button" variant="ghost" color="gray" aria-label={t('common.close')}>
                <Cross2Icon />
              </Button>
            </Dialog.Close>
          </div>

          <div className="prompt-template-source-tabs" role="tablist">
            {(['builtin', 'custom'] as const).map((candidate) => (
              <button
                type="button"
                role="tab"
                aria-selected={source === candidate}
                className={source === candidate ? 'is-active' : ''}
                onClick={() => setSource(candidate)}
                key={candidate}
              >
                {t(`chat.templates.source.${candidate}`)}
                <span>
                  {candidate === 'builtin' ? builtinTemplates.length : customListItems.length}
                </span>
              </button>
            ))}
          </div>

          <div className="prompt-template-controls">
            <label className="prompt-template-search">
              <MagnifyingGlassIcon aria-hidden="true" />
              <TextField.Root
                ref={searchRef}
                value={query}
                aria-label={t('chat.templates.search')}
                placeholder={t('chat.templates.searchPlaceholder')}
                onChange={(event) => setQuery(event.currentTarget.value)}
              />
            </label>
            <div className="prompt-template-categories" aria-label={t('chat.templates.categories')}>
              {CATEGORIES.map((candidate) => (
                <button
                  type="button"
                  className={category === candidate ? 'is-active' : ''}
                  aria-pressed={category === candidate}
                  onClick={() => setCategory(candidate)}
                  key={candidate}
                >
                  {t(`chat.templates.category.${candidate}`)}
                </button>
              ))}
            </div>
          </div>

          <div className="prompt-template-summary" aria-live="polite">
            <span>
              {t('chat.templates.visibleCount', {
                count: visibleTemplates.length,
                total: sourceCount,
              })}
            </span>
            {query || category !== 'all' ? (
              <button type="button" onClick={resetFilters}>
                {t('chat.templates.resetFilters')}
              </button>
            ) : null}
          </div>

          {catalogErrorKey ? (
            <div className="prompt-template-error" role="alert">
              <span>{t(catalogErrorKey)}</span>
              {catalogStatus === 'error' ? (
                <Button
                  type="button"
                  size="1"
                  variant="soft"
                  onClick={() => setRetryRevision((current) => current + 1)}
                >
                  <ReloadIcon />
                  {t('chat.templates.retry')}
                </Button>
              ) : null}
            </div>
          ) : null}

          {source === 'custom' && catalogStatus === 'loading' ? (
            <div className="prompt-template-state" aria-live="polite">
              {t('chat.templates.loading')}
            </div>
          ) : null}

          {visibleTemplates.length ? (
            <div className="prompt-template-grid">
              {visibleTemplates.map((template) => (
                <article
                  className={`prompt-template-card is-${template.category}`}
                  key={template.key}
                >
                  <button
                    type="button"
                    className="prompt-template-select"
                    onClick={() => chooseTemplate(template)}
                  >
                    <span className="prompt-template-card-header">
                      <strong>{template.title}</strong>
                      <small>{t(`chat.templates.category.${template.category}`)}</small>
                    </span>
                    <span className="prompt-template-preview">{template.content}</span>
                    <span className="prompt-template-owner">
                      {t(`chat.templates.owner.${template.source}`)}
                    </span>
                  </button>
                  {template.canDelete ? (
                    <button
                      type="button"
                      className="prompt-template-delete"
                      aria-label={t('chat.templates.deleteTemplate', {
                        title: template.title,
                      })}
                      title={t('chat.templates.deleteTemplate', {
                        title: template.title,
                      })}
                      onClick={() =>
                        setDeleteSelection({
                          template,
                          selectionScopeKey: scopeKey,
                        })
                      }
                    >
                      <TrashIcon aria-hidden="true" />
                    </button>
                  ) : null}
                </article>
              ))}
            </div>
          ) : source !== 'custom' || catalogStatus !== 'loading' ? (
            <div className="prompt-template-state" aria-live="polite">
              <strong>{t('chat.templates.emptyTitle')}</strong>
              <span>{t('chat.templates.emptyDescription')}</span>
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={Boolean(variableSelection)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setVariableSelection(null);
            setMissingVariables(new Set());
          }
        }}
      >
        <Dialog.Content className="prompt-template-variable-dialog" maxWidth="560px">
          <Dialog.Title>{variableSelection?.template.title ?? ''}</Dialog.Title>
          <Dialog.Description>{t('chat.templates.fillVariables')}</Dialog.Description>
          <div className="prompt-template-variable-fields">
            {variableFields.map((variable, index) => {
              const fieldId = `prompt-template-variable-${variable.name}`;
              const hasError = missingVariables.has(variable.name);
              return (
                <label htmlFor={fieldId} key={variable.name}>
                  <span>
                    {variable.name}
                    {variable.required ? <b aria-hidden="true">*</b> : null}
                  </span>
                  {variable.description ? <small>{variable.description}</small> : null}
                  <TextField.Root
                    id={fieldId}
                    autoFocus={index === 0}
                    value={variableValues[variable.name] ?? ''}
                    placeholder={variable.default_value || variable.name}
                    aria-required={variable.required}
                    aria-invalid={hasError}
                    onChange={(event) => {
                      const nextValue = event.currentTarget.value;
                      setVariableValues((current) => ({
                        ...current,
                        [variable.name]: nextValue,
                      }));
                      if (hasError) {
                        setMissingVariables((current) => {
                          const next = new Set(current);
                          next.delete(variable.name);
                          return next;
                        });
                      }
                    }}
                  />
                  {hasError ? (
                    <small className="prompt-template-field-error" role="alert">
                      {t('chat.templates.variableRequired', {
                        name: variable.name,
                      })}
                    </small>
                  ) : null}
                </label>
              );
            })}
          </div>
          <label className="prompt-template-variable-preview">
            <span>{t('chat.templates.preview')}</span>
            <TextArea value={variablePreview} readOnly resize="vertical" rows={5} />
          </label>
          <div className="prompt-template-dialog-actions">
            <Dialog.Close>
              <Button type="button" variant="soft" color="gray">
                {t('common.cancel')}
              </Button>
            </Dialog.Close>
            <Button type="button" onClick={submitVariables}>
              {t('chat.templates.useTemplate')}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root
        open={Boolean(deleteSelection)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen && !deleteBusy) setDeleteSelection(null);
        }}
      >
        <AlertDialog.Content maxWidth="440px">
          <AlertDialog.Title>{t('chat.templates.deleteConfirmTitle')}</AlertDialog.Title>
          <AlertDialog.Description>
            {t('chat.templates.deleteConfirmDescription', {
              title: deleteSelection?.template.title ?? '',
            })}
          </AlertDialog.Description>
          <div className="prompt-template-dialog-actions">
            <AlertDialog.Cancel>
              <Button type="button" variant="soft" color="gray" disabled={deleteBusy}>
                {t('common.cancel')}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                type="button"
                color="red"
                disabled={deleteBusy}
                onClick={(event) => {
                  event.preventDefault();
                  void confirmDelete();
                }}
              >
                <TrashIcon />
                {deleteBusy ? t('chat.templates.deleting') : t('chat.templates.delete')}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}

function translatedOrFallback(value: string, key: string, fallback: string): string {
  return value === key ? fallback : value;
}

function normalizeCategory(category: string): Exclude<PromptTemplateCategoryFilter, 'all'> {
  if (category === 'analysis' || category === 'code' || category === 'writing') {
    return category;
  }
  return 'general';
}
