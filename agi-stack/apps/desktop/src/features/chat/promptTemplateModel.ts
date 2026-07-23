import type { PromptTemplateVariable } from '../../types';

export type PromptTemplateCategory = 'analysis' | 'code' | 'writing' | 'general';
export type PromptTemplateCategoryFilter = PromptTemplateCategory | 'all';
export type PromptTemplateSource = 'builtin' | 'custom';
export type PromptTemplateSourceFilter = PromptTemplateSource | 'all';

export type PromptTemplateListItem = {
  key: string;
  id: string;
  source: PromptTemplateSource;
  title: string;
  content: string;
  category: PromptTemplateCategory;
  variables: PromptTemplateVariable[];
  canDelete: boolean;
};

export type BuiltinPromptTemplate = {
  id: string;
  titleKey: string;
  titleFallback: string;
  contentKey: string;
  contentFallback: string;
  category: PromptTemplateCategory;
};

export const BUILTIN_PROMPT_TEMPLATES: readonly BuiltinPromptTemplate[] = [
  {
    id: 'analyze-codebase',
    titleKey: 'chat.templates.builtin.analyzeCodebase',
    titleFallback: 'Analyze Codebase',
    contentKey: 'chat.templates.builtin.analyzeCodebasePrompt',
    contentFallback:
      'Analyze the codebase structure and provide a high-level overview including architecture patterns, key dependencies, and areas for improvement.',
    category: 'analysis',
  },
  {
    id: 'find-bugs',
    titleKey: 'chat.templates.builtin.findBugs',
    titleFallback: 'Find Bugs',
    contentKey: 'chat.templates.builtin.findBugsPrompt',
    contentFallback:
      'Search for potential bugs, security vulnerabilities, and code quality issues in the project. Focus on critical issues first.',
    category: 'analysis',
  },
  {
    id: 'performance-audit',
    titleKey: 'chat.templates.builtin.performanceAudit',
    titleFallback: 'Performance Audit',
    contentKey: 'chat.templates.builtin.performanceAuditPrompt',
    contentFallback:
      'Analyze the application for performance bottlenecks including database queries, API response times, memory usage, and frontend rendering.',
    category: 'analysis',
  },
  {
    id: 'write-tests',
    titleKey: 'chat.templates.builtin.writeTests',
    titleFallback: 'Write Tests',
    contentKey: 'chat.templates.builtin.writeTestsPrompt',
    contentFallback:
      'Write comprehensive unit tests for the most critical modules. Aim for 80%+ coverage with meaningful test cases.',
    category: 'code',
  },
  {
    id: 'refactor-code',
    titleKey: 'chat.templates.builtin.refactorCode',
    titleFallback: 'Refactor Code',
    contentKey: 'chat.templates.builtin.refactorCodePrompt',
    contentFallback:
      'Identify and refactor code that violates DRY, SOLID principles, or has high complexity. Propose cleaner alternatives.',
    category: 'code',
  },
  {
    id: 'add-feature',
    titleKey: 'chat.templates.builtin.addFeature',
    titleFallback: 'Add Feature',
    contentKey: 'chat.templates.builtin.addFeaturePrompt',
    contentFallback:
      'I want to add a new feature: [describe feature]. Plan the implementation, identify files to modify, and implement it step by step.',
    category: 'code',
  },
  {
    id: 'fix-error',
    titleKey: 'chat.templates.builtin.fixError',
    titleFallback: 'Fix Error',
    contentKey: 'chat.templates.builtin.fixErrorPrompt',
    contentFallback: "I'm getting this error: [paste error]. Diagnose the root cause and fix it.",
    category: 'code',
  },
  {
    id: 'write-docs',
    titleKey: 'chat.templates.builtin.writeDocs',
    titleFallback: 'Write Documentation',
    contentKey: 'chat.templates.builtin.writeDocsPrompt',
    contentFallback:
      'Generate comprehensive documentation for the project including API reference, setup guide, and architecture overview.',
    category: 'writing',
  },
  {
    id: 'write-readme',
    titleKey: 'chat.templates.builtin.writeReadme',
    titleFallback: 'Write README',
    contentKey: 'chat.templates.builtin.writeReadmePrompt',
    contentFallback:
      'Create or improve the project README with sections for: overview, quick start, installation, configuration, usage examples, and contributing.',
    category: 'writing',
  },
  {
    id: 'explain-code',
    titleKey: 'chat.templates.builtin.explainCode',
    titleFallback: 'Explain Code',
    contentKey: 'chat.templates.builtin.explainCodePrompt',
    contentFallback:
      'Explain how the core system works, walking through the main execution flow from entry point to key outputs.',
    category: 'general',
  },
  {
    id: 'brainstorm',
    titleKey: 'chat.templates.builtin.brainstorm',
    titleFallback: 'Brainstorm Ideas',
    contentKey: 'chat.templates.builtin.brainstormPrompt',
    contentFallback:
      'Help me brainstorm ideas for improving this project. Consider UX improvements, new features, technical debt reduction, and scalability.',
    category: 'general',
  },
] as const;

export function filterPromptTemplates(
  templates: readonly PromptTemplateListItem[],
  filters: {
    source: PromptTemplateSourceFilter;
    category: PromptTemplateCategoryFilter;
    query: string;
  },
): PromptTemplateListItem[] {
  const normalizedQuery = filters.query.trim().toLocaleLowerCase();
  return templates.filter((template) => {
    if (filters.source !== 'all' && template.source !== filters.source) return false;
    if (filters.category !== 'all' && template.category !== filters.category) return false;
    if (!normalizedQuery) return true;
    return `${template.title}\n${template.content}\n${promptTemplateVariableFields(
      template.content,
      template.variables,
    )
      .map((variable) => `${variable.name}\n${variable.description}\n${variable.default_value}`)
      .join('\n')}`
      .toLocaleLowerCase()
      .includes(normalizedQuery);
  });
}

export function promptTemplateVariableFields(
  content: string,
  declaredVariables: readonly PromptTemplateVariable[],
): PromptTemplateVariable[] {
  const declaredByName = new Map(
    declaredVariables.map((variable) => [variable.name, variable] as const),
  );
  const seen = new Set<string>();
  const fields: PromptTemplateVariable[] = [];
  for (const match of content.matchAll(/\{\{(\w+)\}\}/g)) {
    const name = match[1];
    if (!name || seen.has(name)) continue;
    seen.add(name);
    fields.push(
      declaredByName.get(name) ?? {
        name,
        description: '',
        default_value: '',
        required: false,
      },
    );
  }
  return fields;
}

export function resolvePromptTemplate(
  content: string,
  variables: readonly PromptTemplateVariable[],
  values: Readonly<Record<string, string>>,
): { content: string | null; missingRequired: string[] } {
  const missingRequired = variables
    .filter((variable) => variable.required && !(values[variable.name] ?? '').trim())
    .map((variable) => variable.name);
  if (missingRequired.length) return { content: null, missingRequired };

  let resolved = content;
  for (const variable of variables) {
    const value = values[variable.name] ?? '';
    if (value) resolved = resolved.replaceAll(`{{${variable.name}}}`, value);
  }
  return { content: resolved, missingRequired: [] };
}

export function promptTemplateRequestMatches(input: {
  requestId: number;
  currentRequestId: number;
  expectedScopeKey: string;
  currentScopeKey: string;
}): boolean {
  return (
    Boolean(input.expectedScopeKey) &&
    input.requestId === input.currentRequestId &&
    input.expectedScopeKey === input.currentScopeKey
  );
}

export function promptTemplateErrorKey(status: number | undefined): string {
  if (status === 401) return 'chat.templates.authenticationRequired';
  if (status === 403) return 'chat.templates.permissionDenied';
  if (status === 409) return 'chat.templates.conflict';
  if (status === 422) return 'chat.templates.validationFailed';
  return 'chat.templates.loadFailed';
}
