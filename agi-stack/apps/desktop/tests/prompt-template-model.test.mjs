import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  filterPromptTemplates,
  promptTemplatePreview,
  promptTemplateErrorKey,
  promptTemplateRequestMatches,
  promptTemplateSaveErrorKey,
  promptTemplateVariableFields,
  resolvePromptTemplate,
  validatePromptTemplateDraft,
} = require('/tmp/agistack-desktop-test-dist/src/features/chat/promptTemplateModel.js');

const readSource = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const templateLibrarySource = readSource('features/chat/PromptTemplateLibrary.tsx');
const saveDialogSource = readSource('features/chat/SavePromptTemplateDialog.tsx');
const chatPanelSource = readSource('features/chat/ChatPanel.tsx');
const catalogSource = readSource('features/chat/composerCatalogModel.ts');
const chatStyles = readSource('features/chat/ComposerMenus.css');
const i18nSource = readSource('i18n.tsx');

const builtInTemplate = {
  key: 'builtin:analyze-codebase',
  id: 'analyze-codebase',
  source: 'builtin',
  title: 'Analyze codebase',
  content: 'Analyze the architecture.',
  category: 'analysis',
  variables: [],
  canDelete: false,
};

const customTemplate = {
  key: 'custom:template-1',
  id: 'template-1',
  source: 'custom',
  title: 'Release brief',
  content: 'Summarize {{release}} for {{audience}}.',
  category: 'writing',
  variables: [
    {
      name: 'release',
      description: 'Release identifier',
      default_value: '',
      required: true,
    },
    {
      name: 'audience',
      description: 'Reader group',
      default_value: 'engineering',
      required: false,
    },
  ],
  canDelete: true,
};

test('template filtering preserves source, category, search, and deterministic ordering', () => {
  const customAnalysis = {
    ...customTemplate,
    key: 'custom:template-2',
    id: 'template-2',
    title: 'Architecture review',
    content: 'Review service boundaries.',
    category: 'analysis',
  };
  const templates = [builtInTemplate, customTemplate, customAnalysis];

  assert.deepEqual(
    filterPromptTemplates(templates, {
      source: 'all',
      category: 'analysis',
      query: '',
    }).map((template) => template.key),
    ['builtin:analyze-codebase', 'custom:template-2'],
  );
  assert.deepEqual(
    filterPromptTemplates(templates, {
      source: 'custom',
      category: 'all',
      query: 'engineering',
    }).map((template) => template.key),
    ['custom:template-1'],
  );
  assert.deepEqual(
    filterPromptTemplates(templates, {
      source: 'builtin',
      category: 'all',
      query: 'RELEASE',
    }),
    [],
  );
});

test('variable fields keep first-use order and merge authoritative definitions', () => {
  assert.deepEqual(
    promptTemplateVariableFields(
      'Ship {{release}} to {{audience}}. Re-check {{release}} with {{optional_note}}.',
      customTemplate.variables,
    ),
    [
      {
        name: 'release',
        description: 'Release identifier',
        default_value: '',
        required: true,
      },
      {
        name: 'audience',
        description: 'Reader group',
        default_value: 'engineering',
        required: false,
      },
      {
        name: 'optional_note',
        description: '',
        default_value: '',
        required: false,
      },
    ],
  );
});

test('template interpolation validates required variables and replaces repeated tokens', () => {
  assert.deepEqual(
    resolvePromptTemplate(
      'Ship {{release}} to {{audience}}; verify {{release}}. {{optional_note}}',
      promptTemplateVariableFields(
        'Ship {{release}} to {{audience}}; verify {{release}}. {{optional_note}}',
        customTemplate.variables,
      ),
      { release: '', audience: 'product', optional_note: '' },
    ),
    {
      content: null,
      missingRequired: ['release'],
    },
  );
  assert.deepEqual(
    resolvePromptTemplate(
      'Ship {{release}} to {{audience}}; verify {{release}}. {{optional_note}}',
      promptTemplateVariableFields(
        'Ship {{release}} to {{audience}}; verify {{release}}. {{optional_note}}',
        customTemplate.variables,
      ),
      { release: '2026.7', audience: 'product', optional_note: '' },
    ),
    {
      content: 'Ship 2026.7 to product; verify 2026.7. {{optional_note}}',
      missingRequired: [],
    },
  );
});

test('late catalog and interpolation results stay bound to their captured composer scope', () => {
  assert.equal(
    promptTemplateRequestMatches({
      requestId: 4,
      currentRequestId: 4,
      expectedScopeKey: 'tenant-1:project-1:conversation-1',
      currentScopeKey: 'tenant-1:project-1:conversation-1',
    }),
    true,
  );
  assert.equal(
    promptTemplateRequestMatches({
      requestId: 3,
      currentRequestId: 4,
      expectedScopeKey: 'tenant-1:project-1:conversation-1',
      currentScopeKey: 'tenant-1:project-1:conversation-1',
    }),
    false,
  );
  assert.equal(
    promptTemplateRequestMatches({
      requestId: 4,
      currentRequestId: 4,
      expectedScopeKey: 'tenant-1:project-1:conversation-1',
      currentScopeKey: 'tenant-2:project-2:conversation-2',
    }),
    false,
  );
});

test('template failures map protocol status to localized actionable states', () => {
  assert.equal(promptTemplateErrorKey(401), 'chat.templates.authenticationRequired');
  assert.equal(promptTemplateErrorKey(403), 'chat.templates.permissionDenied');
  assert.equal(promptTemplateErrorKey(409), 'chat.templates.conflict');
  assert.equal(promptTemplateErrorKey(422), 'chat.templates.validationFailed');
  assert.equal(promptTemplateErrorKey(500), 'chat.templates.loadFailed');
  assert.equal(promptTemplateErrorKey(undefined), 'chat.templates.loadFailed');
});

test('save-template drafts require a trimmed title and exact non-empty assistant content', () => {
  assert.deepEqual(
    validatePromptTemplateDraft({
      title: '  Release answer  ',
      content: 'Exact assistant answer\nwith details.',
      category: 'analysis',
    }),
    {
      ok: true,
      value: {
        title: 'Release answer',
        content: 'Exact assistant answer\nwith details.',
        category: 'analysis',
      },
    },
  );
  assert.deepEqual(
    validatePromptTemplateDraft({
      title: '   ',
      content: 'Assistant answer',
      category: 'general',
    }),
    { ok: false, errorKey: 'chat.templates.saveTitleRequired' },
  );
  assert.deepEqual(
    validatePromptTemplateDraft({
      title: 'Answer',
      content: '   ',
      category: 'general',
    }),
    { ok: false, errorKey: 'chat.templates.saveContentRequired' },
  );
});

test('save-template preview and failure mapping match the Web-visible contract', () => {
  assert.equal(promptTemplatePreview('x'.repeat(199)), 'x'.repeat(199));
  assert.equal(promptTemplatePreview('x'.repeat(201)), `${'x'.repeat(200)}…`);
  assert.equal(promptTemplateSaveErrorKey(401), 'chat.templates.authenticationRequired');
  assert.equal(promptTemplateSaveErrorKey(403), 'chat.templates.permissionDenied');
  assert.equal(promptTemplateSaveErrorKey(409), 'chat.templates.conflict');
  assert.equal(promptTemplateSaveErrorKey(422), 'chat.templates.validationFailed');
  assert.equal(promptTemplateSaveErrorKey(500), 'chat.templates.saveFailed');
  assert.equal(promptTemplateSaveErrorKey(undefined), 'chat.templates.saveFailed');
});

test('Desktop template library preserves Web behavior and renderer security boundaries', () => {
  assert.match(chatPanelSource, /<PromptTemplateLibrary/);
  assert.match(templateLibrarySource, /new AbortController\(\)/);
  assert.match(templateLibrarySource, /requestGenerationRef/);
  assert.match(templateLibrarySource, /refreshToken/);
  assert.match(templateLibrarySource, /listPromptTemplates/);
  assert.match(templateLibrarySource, /deletePromptTemplate/);
  assert.match(templateLibrarySource, /<Dialog\.Root/);
  assert.match(templateLibrarySource, /<AlertDialog\.Root/);
  assert.match(templateLibrarySource, /aria-label=\{t\('chat\.templates\.search'\)\}/);
  assert.match(templateLibrarySource, /aria-live="polite"/);
  assert.match(templateLibrarySource, /role="alert"/);
  assert.match(templateLibrarySource, /selectionScopeKey/);
  assert.match(templateLibrarySource, /const nextValue = event\.currentTarget\.value/);
  assert.doesNotMatch(
    templateLibrarySource,
    /\[variable\.name\]: event\.currentTarget\.value/,
  );
  assert.match(catalogSource, /listPromptTemplates\?/);
  assert.match(catalogSource, /createPromptTemplate\?/);
  assert.match(catalogSource, /deletePromptTemplate\?/);
  assert.match(chatStyles, /\.prompt-template-library/);
  assert.equal(i18nSource.match(/'chat\.templates\.title':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.templates\.useTemplate':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.templates\.deleteConfirmTitle':/g)?.length, 2);
  assert.doesNotMatch(templateLibrarySource, /ipcRenderer|window\.desktop|window\.electron/);
});

test('Desktop save-template dialog preserves exact content and isolates asynchronous writes', () => {
  assert.match(saveDialogSource, /new AbortController\(\)/);
  assert.match(saveDialogSource, /requestGenerationRef/);
  assert.match(saveDialogSource, /promptTemplateRequestMatches\(/);
  assert.match(saveDialogSource, /validatePromptTemplateDraft\(/);
  assert.match(saveDialogSource, /promptTemplatePreview\(target\.content\)/);
  assert.match(saveDialogSource, /createPromptTemplate/);
  assert.match(saveDialogSource, /autoFocus/);
  assert.match(saveDialogSource, /aria-live="polite"/);
  assert.match(saveDialogSource, /role="alert"/);
  assert.match(saveDialogSource, /const nextTitle = event\.currentTarget\.value/);
  assert.doesNotMatch(saveDialogSource, /setTitle\(event\.currentTarget\.value\)/);
  assert.doesNotMatch(saveDialogSource, /ipcRenderer|window\.desktop|window\.electron/);
  assert.equal(i18nSource.match(/'chat\.templates\.saveAsTemplate':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.templates\.saved':/g)?.length, 2);
});
