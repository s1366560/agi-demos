/**
 * Canonical Story (YAML) parser.
 *
 * A workspace task description is "canonical" once it embeds a single fenced
 * `yaml` block matching the schema below. Parsing this contract gives the
 * Kanban gate a deterministic structure to enforce instead of free-form text.
 *
 * Distilled from routa's `src/core/kanban/canonical-story.ts`.
 *
 * @example
 * ```yaml
 * story:
 *   version: 1
 *   language: en
 *   title: Add SSO login
 *   problem_statement: ...
 *   user_value: ...
 *   acceptance_criteria:
 *     - id: AC-1
 *       text: User can log in via Okta
 *       testable: true
 *   constraints_and_affected_areas: []
 *   dependencies_and_sequencing:
 *     independent_story_check: pass
 *     depends_on: []
 *     unblock_condition: ""
 *   out_of_scope: []
 *   invest:
 *     independent: { status: pass, reason: "..." }
 *     ...
 * ```
 */

import yaml from 'js-yaml';

export type CanonicalStoryStatus = 'pass' | 'fail' | 'warning';

export interface CanonicalStoryAcceptanceCriterion {
  id: string;
  text: string;
  testable: boolean;
}

export interface CanonicalStoryInvestCheck {
  status: CanonicalStoryStatus;
  reason: string;
}

export interface CanonicalStoryDocument {
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
    invest: Record<
      'independent' | 'negotiable' | 'valuable' | 'estimable' | 'small' | 'testable',
      CanonicalStoryInvestCheck
    >;
  };
}

export interface CanonicalStoryParseResult {
  hasYamlBlock: boolean;
  story: CanonicalStoryDocument | null;
  issues: string[];
  rawYaml: string | null;
}

const CANONICAL_STORY_REGEX = /```yaml\s*\n([\s\S]*?)\n```/i;
const STATUSES: ReadonlySet<CanonicalStoryStatus> = new Set(['pass', 'fail', 'warning']);
const INVEST_KEYS = [
  'independent',
  'negotiable',
  'valuable',
  'estimable',
  'small',
  'testable',
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown, path: string, issues: string[]): string {
  if (typeof value !== 'string' || !value.trim()) {
    issues.push(`${path} must be a non-empty string`);
    return '';
  }
  return value.trim();
}

function readBoolean(value: unknown, path: string, issues: string[]): boolean {
  if (typeof value !== 'boolean') {
    issues.push(`${path} must be a boolean`);
    return false;
  }
  return value;
}

function readStringArray(
  value: unknown,
  path: string,
  issues: string[],
  options?: { optional?: boolean }
): string[] {
  if ((value === undefined || value === null) && options?.optional) return [];
  if (!Array.isArray(value)) {
    issues.push(`${path} must be an array of strings`);
    return [];
  }
  return value
    .map((item, idx) => readString(item, `${path}[${String(idx)}]`, issues))
    .filter(Boolean);
}

function readStatus(value: unknown, path: string, issues: string[]): CanonicalStoryStatus {
  if (typeof value === 'string' && STATUSES.has(value as CanonicalStoryStatus)) {
    return value as CanonicalStoryStatus;
  }
  issues.push(`${path} must be one of: pass | fail | warning`);
  return 'fail';
}

function readInvestCheck(
  value: unknown,
  path: string,
  issues: string[]
): CanonicalStoryInvestCheck {
  if (!isRecord(value)) {
    issues.push(`${path} must be an object { status, reason }`);
    return { status: 'fail', reason: '' };
  }
  return {
    status: readStatus(value.status, `${path}.status`, issues),
    reason: readString(value.reason, `${path}.reason`, issues),
  };
}

function readAcceptanceCriteria(
  value: unknown,
  issues: string[]
): CanonicalStoryAcceptanceCriterion[] {
  if (!Array.isArray(value) || value.length === 0) {
    issues.push('story.acceptance_criteria must be a non-empty array');
    return [];
  }
  return value.map((item, idx) => {
    const path = `story.acceptance_criteria[${String(idx)}]`;
    if (!isRecord(item)) {
      issues.push(`${path} must be an object { id, text, testable }`);
      return { id: '', text: '', testable: false };
    }
    return {
      id: readString(item.id, `${path}.id`, issues),
      text: readString(item.text, `${path}.text`, issues),
      testable: readBoolean(item.testable, `${path}.testable`, issues),
    };
  });
}

/**
 * Extract and validate the canonical story YAML embedded in `text`.
 *
 * Returns `hasYamlBlock=false` only when no fenced ```yaml block is present.
 * Returns `story=null` when the block is malformed; `issues` lists every
 * structural problem so the gate UI can render actionable diagnostics.
 */
export function parseCanonicalStory(text: string | null | undefined): CanonicalStoryParseResult {
  const empty: CanonicalStoryParseResult = {
    hasYamlBlock: false,
    story: null,
    issues: [],
    rawYaml: null,
  };
  if (!text) return empty;

  const match = CANONICAL_STORY_REGEX.exec(text);
  if (!match?.[1]) return empty;

  const rawYaml = match[1];
  const issues: string[] = [];

  let parsed: unknown;
  try {
    parsed = yaml.load(rawYaml);
  } catch (error) {
    return {
      hasYamlBlock: true,
      story: null,
      rawYaml,
      issues: [`yaml syntax error: ${(error as Error).message}`],
    };
  }

  if (!isRecord(parsed) || !isRecord(parsed.story)) {
    return {
      hasYamlBlock: true,
      story: null,
      rawYaml,
      issues: ['root must be an object with a "story" key'],
    };
  }

  const storyRaw = parsed.story;
  const dependenciesRaw = isRecord(storyRaw.dependencies_and_sequencing)
    ? storyRaw.dependencies_and_sequencing
    : {};
  const independentCheck = dependenciesRaw.independent_story_check;
  const investRaw = isRecord(storyRaw.invest) ? storyRaw.invest : {};

  let storyVersion = 0;
  if (typeof storyRaw.version === 'number' && storyRaw.version > 0) {
    storyVersion = Math.trunc(storyRaw.version);
  } else {
    issues.push('story.version must be a positive number');
  }

  let independentStoryCheck: 'pass' | 'fail' = 'fail';
  if (independentCheck === 'pass' || independentCheck === 'fail') {
    independentStoryCheck = independentCheck;
  } else {
    issues.push('story.dependencies_and_sequencing.independent_story_check must be pass | fail');
  }

  const story: CanonicalStoryDocument = {
    story: {
      version: storyVersion,
      language: readString(storyRaw.language, 'story.language', issues),
      title: readString(storyRaw.title, 'story.title', issues),
      problem_statement: readString(storyRaw.problem_statement, 'story.problem_statement', issues),
      user_value: readString(storyRaw.user_value, 'story.user_value', issues),
      acceptance_criteria: readAcceptanceCriteria(storyRaw.acceptance_criteria, issues),
      constraints_and_affected_areas: readStringArray(
        storyRaw.constraints_and_affected_areas,
        'story.constraints_and_affected_areas',
        issues,
        { optional: true }
      ),
      dependencies_and_sequencing: {
        independent_story_check: independentStoryCheck,
        depends_on: readStringArray(
          dependenciesRaw.depends_on,
          'story.dependencies_and_sequencing.depends_on',
          issues,
          { optional: true }
        ),
        unblock_condition:
          typeof dependenciesRaw.unblock_condition === 'string'
            ? dependenciesRaw.unblock_condition.trim()
            : '',
      },
      out_of_scope: readStringArray(storyRaw.out_of_scope, 'story.out_of_scope', issues, {
        optional: true,
      }),
      invest: INVEST_KEYS.reduce(
        (acc, key) => {
          acc[key] = readInvestCheck(investRaw[key], `story.invest.${key}`, issues);
          return acc;
        },
        {} as CanonicalStoryDocument['story']['invest']
      ),
    },
  };

  return {
    hasYamlBlock: true,
    story: issues.length === 0 ? story : null,
    rawYaml,
    issues,
  };
}

/**
 * True iff the story is parseable AND every INVEST dimension is `pass`.
 * Lane gates can use this as the cheap "ready to advance" check.
 */
export function isStoryReadyToAdvance(result: CanonicalStoryParseResult): boolean {
  const story = result.story;
  if (!story) return false;
  return INVEST_KEYS.every((key) => story.story.invest[key].status === 'pass');
}
