import { parseDocument } from 'yaml';

export type CanonicalStoryStatus = 'pass' | 'fail' | 'warning';

export type CanonicalStoryAcceptanceCriterion = {
  id: string;
  text: string;
  testable: boolean;
};

export type CanonicalStoryInvestCheck = {
  status: CanonicalStoryStatus;
  reason: string;
};

export type CanonicalStoryInvestKey =
  | 'independent'
  | 'negotiable'
  | 'valuable'
  | 'estimable'
  | 'small'
  | 'testable';

export type CanonicalStoryDocument = {
  story: {
    version: number;
    language: string;
    title: string;
    problem_statement: string;
    user_value: string;
    acceptance_criteria: CanonicalStoryAcceptanceCriterion[];
    constraints_and_affected_areas: string[];
    dependencies_and_sequencing: {
      independent_story_check: 'pass' | 'fail';
      depends_on: string[];
      unblock_condition: string;
    };
    out_of_scope: string[];
    invest: Record<CanonicalStoryInvestKey, CanonicalStoryInvestCheck>;
  };
};

export type CanonicalStoryParseResult = {
  story: CanonicalStoryDocument | null;
  issues: string[];
  rawYaml: string;
};

export type CanonicalStoryRenderDecision =
  | { kind: 'card'; result: CanonicalStoryParseResult }
  | { kind: 'code' };

export const CANONICAL_STORY_INVEST_KEYS: readonly CanonicalStoryInvestKey[] = [
  'independent',
  'negotiable',
  'valuable',
  'estimable',
  'small',
  'testable',
];

const CANONICAL_STORY_STATUSES = new Set<CanonicalStoryStatus>([
  'pass',
  'fail',
  'warning',
]);
const MAX_CANONICAL_STORY_SOURCE_LENGTH = 65_536;
const MAX_CANONICAL_STORY_DEPTH = 12;
const MAX_CANONICAL_STORY_NODES = 500;
const MAX_CANONICAL_STORY_COLLECTION_SIZE = 50;
const MAX_CANONICAL_STORY_STRING_LENGTH = 16_384;
const MAX_REPORTED_ISSUES = 50;
const DANGEROUS_OBJECT_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

export function canonicalStoryRenderDecision(
  language: string,
  rawYaml: string,
): CanonicalStoryRenderDecision {
  const normalizedLanguage = language.trim().toLowerCase();
  if (normalizedLanguage !== 'canonical-story' && normalizedLanguage !== 'yaml') {
    return { kind: 'code' };
  }
  const result = parseCanonicalStory(rawYaml);
  if (normalizedLanguage === 'canonical-story' || result.story) {
    return { kind: 'card', result };
  }
  return { kind: 'code' };
}

export function parseCanonicalStory(rawYaml: string): CanonicalStoryParseResult {
  if (rawYaml.length > MAX_CANONICAL_STORY_SOURCE_LENGTH) {
    return invalidResult(rawYaml, [
      `source_too_long:${String(MAX_CANONICAL_STORY_SOURCE_LENGTH)}`,
    ]);
  }

  let parsed: unknown;
  try {
    const document = parseDocument(rawYaml, {
      customTags: [],
      logLevel: 'silent',
      merge: false,
      prettyErrors: false,
      resolveKnownTags: false,
      schema: 'core',
      strict: true,
      stringKeys: true,
      uniqueKeys: true,
      version: '1.2',
    });
    if (document.errors.length > 0 || document.warnings.length > 0) {
      return invalidResult(rawYaml, ['parse_error']);
    }
    try {
      parsed = document.toJS({ maxAliasCount: 0 });
    } catch {
      return invalidResult(rawYaml, ['aliases_forbidden']);
    }
  } catch {
    return invalidResult(rawYaml, ['parse_error']);
  }

  const resourceIssues = structuredValueIssues(parsed);
  if (resourceIssues.length > 0) return invalidResult(rawYaml, resourceIssues);

  const issues: string[] = [];
  if (!isRecord(parsed)) {
    return invalidResult(rawYaml, ['object_required:document']);
  }
  const root = parsed.story;
  if (!isRecord(root)) {
    return invalidResult(rawYaml, ['object_required:story']);
  }

  const version = readPositiveInteger(root.version, 'story.version', issues);
  const language = readString(root.language, 'story.language', issues);
  const title = readString(root.title, 'story.title', issues);
  const problemStatement = readString(
    root.problem_statement,
    'story.problem_statement',
    issues,
  );
  const userValue = readString(root.user_value, 'story.user_value', issues);
  const acceptanceCriteria = readAcceptanceCriteria(
    root.acceptance_criteria,
    'story.acceptance_criteria',
    issues,
  );
  const constraints = readStringArray(
    root.constraints_and_affected_areas,
    'story.constraints_and_affected_areas',
    issues,
  );
  const dependencies = readDependencies(
    root.dependencies_and_sequencing,
    'story.dependencies_and_sequencing',
    issues,
  );
  const outOfScope = readStringArray(root.out_of_scope, 'story.out_of_scope', issues, true);
  const invest = readInvest(root.invest, 'story.invest', issues);

  if (issues.length > 0) return invalidResult(rawYaml, issues);
  return {
    story: {
      story: {
        version,
        language,
        title,
        problem_statement: problemStatement,
        user_value: userValue,
        acceptance_criteria: acceptanceCriteria,
        constraints_and_affected_areas: constraints,
        dependencies_and_sequencing: dependencies,
        out_of_scope: outOfScope,
        invest,
      },
    },
    issues: [],
    rawYaml,
  };
}

function invalidResult(rawYaml: string, issues: string[]): CanonicalStoryParseResult {
  return {
    story: null,
    issues: issues.slice(0, MAX_REPORTED_ISSUES),
    rawYaml,
  };
}

function structuredValueIssues(value: unknown): string[] {
  const issues: string[] = [];
  const state = { nodes: 0 };

  const visit = (current: unknown, path: string, depth: number): void => {
    if (issues.length >= MAX_REPORTED_ISSUES) return;
    state.nodes += 1;
    if (state.nodes > MAX_CANONICAL_STORY_NODES) {
      issues.push(`value_limit:${String(MAX_CANONICAL_STORY_NODES)}`);
      return;
    }
    if (depth > MAX_CANONICAL_STORY_DEPTH) {
      issues.push(`depth_limit:${String(MAX_CANONICAL_STORY_DEPTH)}`);
      return;
    }
    if (typeof current === 'string') {
      if (current.length > MAX_CANONICAL_STORY_STRING_LENGTH) {
        issues.push(
          `string_too_long:${path}:${String(MAX_CANONICAL_STORY_STRING_LENGTH)}`,
        );
      }
      return;
    }
    if (Array.isArray(current)) {
      if (current.length > MAX_CANONICAL_STORY_COLLECTION_SIZE) {
        issues.push(
          `collection_limit:${path}:${String(MAX_CANONICAL_STORY_COLLECTION_SIZE)}`,
        );
        return;
      }
      current.forEach((item, index) => visit(item, `${path}[${String(index)}]`, depth + 1));
      return;
    }
    if (!isRecord(current)) return;
    const entries = Object.entries(current);
    if (entries.length > MAX_CANONICAL_STORY_COLLECTION_SIZE) {
      issues.push(`field_limit:${path}:${String(MAX_CANONICAL_STORY_COLLECTION_SIZE)}`);
      return;
    }
    for (const [key, item] of entries) {
      if (DANGEROUS_OBJECT_KEYS.has(key)) {
        issues.push(`prohibited_field:${path}`);
        continue;
      }
      visit(item, `${path}.${key}`, depth + 1);
    }
  };

  visit(value, 'story document', 0);
  return issues;
}

function readPositiveInteger(value: unknown, path: string, issues: string[]): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
    issues.push(`positive_integer_required:${path}`);
    return 1;
  }
  return value;
}

function readString(value: unknown, path: string, issues: string[]): string {
  if (typeof value !== 'string' || !value.trim()) {
    issues.push(`string_required:${path}`);
    return '';
  }
  return value.trim();
}

function readBoolean(value: unknown, path: string, issues: string[]): boolean {
  if (typeof value !== 'boolean') {
    issues.push(`boolean_required:${path}`);
    return false;
  }
  return value;
}

function readStringArray(
  value: unknown,
  path: string,
  issues: string[],
  optional = false,
): string[] {
  if ((value === null || value === undefined) && optional) return [];
  if (!Array.isArray(value)) {
    issues.push(`string_array_required:${path}`);
    return [];
  }
  if (!optional && value.length === 0) {
    issues.push(`item_required:${path}`);
  }
  return value.map((item, index) => readString(item, `${path}[${String(index)}]`, issues));
}

function readAcceptanceCriteria(
  value: unknown,
  path: string,
  issues: string[],
): CanonicalStoryAcceptanceCriterion[] {
  if (!Array.isArray(value)) {
    issues.push(`array_required:${path}`);
    return [];
  }
  if (value.length < 2) issues.push(`minimum_items:${path}:2`);
  const ids = new Set<string>();
  return value.flatMap((item, index) => {
    const itemPath = `${path}[${String(index)}]`;
    if (!isRecord(item)) {
      issues.push(`object_required:${itemPath}`);
      return [];
    }
    const id = readString(item.id, `${itemPath}.id`, issues);
    if (id && ids.has(id)) issues.push(`acceptance_ids_not_unique:${path}`);
    ids.add(id);
    return [
      {
        id,
        text: readString(item.text, `${itemPath}.text`, issues),
        testable: readBoolean(item.testable, `${itemPath}.testable`, issues),
      },
    ];
  });
}

function readDependencies(
  value: unknown,
  path: string,
  issues: string[],
): CanonicalStoryDocument['story']['dependencies_and_sequencing'] {
  if (!isRecord(value)) {
    issues.push(`object_required:${path}`);
    return {
      independent_story_check: 'fail',
      depends_on: [],
      unblock_condition: '',
    };
  }
  const independent =
    value.independent_story_check === 'pass' || value.independent_story_check === 'fail'
      ? value.independent_story_check
      : 'fail';
  if (
    value.independent_story_check !== 'pass' &&
    value.independent_story_check !== 'fail'
  ) {
    issues.push(`pass_fail_required:${path}.independent_story_check`);
  }
  return {
    independent_story_check: independent,
    depends_on: readStringArray(value.depends_on, `${path}.depends_on`, issues, true),
    unblock_condition: readString(value.unblock_condition, `${path}.unblock_condition`, issues),
  };
}

function readInvest(
  value: unknown,
  path: string,
  issues: string[],
): Record<CanonicalStoryInvestKey, CanonicalStoryInvestCheck> {
  const fallback = (): CanonicalStoryInvestCheck => ({ status: 'fail', reason: '' });
  if (!isRecord(value)) {
    issues.push(`object_required:${path}`);
    return {
      independent: fallback(),
      negotiable: fallback(),
      valuable: fallback(),
      estimable: fallback(),
      small: fallback(),
      testable: fallback(),
    };
  }
  return Object.fromEntries(
    CANONICAL_STORY_INVEST_KEYS.map((key) => {
      const check = value[key];
      const checkPath = `${path}.${key}`;
      if (!isRecord(check)) {
        issues.push(`object_required:${checkPath}`);
        return [key, fallback()];
      }
      const status =
        typeof check.status === 'string' &&
        CANONICAL_STORY_STATUSES.has(check.status as CanonicalStoryStatus)
          ? (check.status as CanonicalStoryStatus)
          : 'fail';
      if (
        typeof check.status !== 'string' ||
        !CANONICAL_STORY_STATUSES.has(check.status as CanonicalStoryStatus)
      ) {
        issues.push(`story_status_required:${checkPath}.status`);
      }
      return [
        key,
        {
          status,
          reason: readString(check.reason, `${checkPath}.reason`, issues),
        },
      ];
    }),
  ) as Record<CanonicalStoryInvestKey, CanonicalStoryInvestCheck>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
