/**
 * Canonical Story schema + parser.
 *
 * A "Canonical Story" is a structured YAML block embedded in a markdown
 * fenced code block (```yaml). It captures problem statement, acceptance
 * criteria, INVEST checks, and dependency / sequencing metadata so the UI
 * can render a rich card instead of a wall of text.
 *
 * Distilled from Routa's `src/core/kanban/canonical-story.ts`.
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
    invest: {
      independent: CanonicalStoryInvestCheck;
      negotiable: CanonicalStoryInvestCheck;
      valuable: CanonicalStoryInvestCheck;
      estimable: CanonicalStoryInvestCheck;
      small: CanonicalStoryInvestCheck;
      testable: CanonicalStoryInvestCheck;
    };
  };
}

export interface CanonicalStoryParseResult {
  story: CanonicalStoryDocument | null;
  issues: string[];
  rawYaml: string;
}

const CANONICAL_STORY_STATUS = new Set<CanonicalStoryStatus>(['pass', 'fail', 'warning']);
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
  options?: { optional?: boolean; allowEmpty?: boolean }
): string[] {
  const optional = options?.optional ?? false;
  const allowEmpty = options?.allowEmpty ?? false;
  if ((value === undefined || value === null) && optional) return [];
  if (!Array.isArray(value)) {
    issues.push(`${path} must be an array of strings`);
    return [];
  }
  const items = value
    .map((item, idx) => readString(item, `${path}[${String(idx)}]`, issues))
    .filter(Boolean);
  if (!allowEmpty && items.length === 0) {
    issues.push(`${path} must contain at least one non-empty string`);
  }
  return items;
}

function readAcceptanceCriteria(
  value: unknown,
  path: string,
  issues: string[]
): CanonicalStoryAcceptanceCriterion[] {
  if (!Array.isArray(value)) {
    issues.push(`${path} must be an array`);
    return [];
  }
  const out = value.flatMap((item, idx): CanonicalStoryAcceptanceCriterion[] => {
    if (!isRecord(item)) {
      issues.push(`${path}[${String(idx)}] must be an object`);
      return [];
    }
    return [
      {
        id: readString(item.id, `${path}[${String(idx)}].id`, issues),
        text: readString(item.text, `${path}[${String(idx)}].text`, issues),
        testable: readBoolean(item.testable, `${path}[${String(idx)}].testable`, issues),
      },
    ];
  });
  if (out.length < 2) issues.push(`${path} must contain at least 2 acceptance criteria`);
  return out;
}

function readInvestCheck(
  value: unknown,
  path: string,
  issues: string[]
): CanonicalStoryInvestCheck {
  if (!isRecord(value)) {
    issues.push(`${path} must be an object`);
    return { status: 'fail', reason: '' };
  }
  const statusStr = readString(value.status, `${path}.status`, issues) as CanonicalStoryStatus;
  if (!CANONICAL_STORY_STATUS.has(statusStr)) {
    issues.push(`${path}.status must be one of: pass, fail, warning`);
  }
  return {
    status: CANONICAL_STORY_STATUS.has(statusStr) ? statusStr : 'fail',
    reason: readString(value.reason, `${path}.reason`, issues),
  };
}

/**
 * True if the raw yaml content looks like a canonical-story block — used to
 * cheaply gate parsing without taking the cost of a full yaml load on every
 * fenced code block.
 */
export function looksLikeCanonicalStory(rawYaml: string): boolean {
  return /^\s*story\s*:/m.test(rawYaml);
}

export function parseCanonicalStory(rawYaml: string): CanonicalStoryParseResult {
  let parsed: unknown;
  try {
    parsed = yaml.load(rawYaml);
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    return { story: null, issues: [`Failed to parse YAML: ${msg}`], rawYaml };
  }

  const issues: string[] = [];
  if (!isRecord(parsed)) {
    return { story: null, issues: ['Canonical story root must be an object'], rawYaml };
  }
  const root = parsed.story;
  if (!isRecord(root)) {
    return { story: null, issues: ['story must be an object'], rawYaml };
  }

  const version = root.version;
  if (typeof version !== 'number' || !Number.isInteger(version) || version < 1) {
    issues.push('story.version must be a positive integer');
  }

  const dependencies = root.dependencies_and_sequencing;
  const invest = root.invest;
  if (!isRecord(dependencies)) issues.push('story.dependencies_and_sequencing must be an object');
  if (!isRecord(invest)) issues.push('story.invest must be an object');

  const story: CanonicalStoryDocument = {
    story: {
      version:
        typeof version === 'number' && Number.isInteger(version) && version > 0 ? version : 1,
      language: readString(root.language, 'story.language', issues),
      title: readString(root.title, 'story.title', issues),
      problem_statement: readString(root.problem_statement, 'story.problem_statement', issues),
      user_value: readString(root.user_value, 'story.user_value', issues),
      acceptance_criteria: readAcceptanceCriteria(
        root.acceptance_criteria,
        'story.acceptance_criteria',
        issues
      ),
      constraints_and_affected_areas: readStringArray(
        root.constraints_and_affected_areas,
        'story.constraints_and_affected_areas',
        issues
      ),
      dependencies_and_sequencing: {
        independent_story_check:
          isRecord(dependencies) &&
          (dependencies.independent_story_check === 'pass' ||
            dependencies.independent_story_check === 'fail')
            ? dependencies.independent_story_check
            : 'fail',
        depends_on: isRecord(dependencies)
          ? readStringArray(
              dependencies.depends_on,
              'story.dependencies_and_sequencing.depends_on',
              issues,
              { optional: true, allowEmpty: true }
            )
          : [],
        unblock_condition: isRecord(dependencies)
          ? readString(
              dependencies.unblock_condition,
              'story.dependencies_and_sequencing.unblock_condition',
              issues
            )
          : '',
      },
      out_of_scope: readStringArray(root.out_of_scope, 'story.out_of_scope', issues, {
        optional: true,
        allowEmpty: true,
      }),
      invest: {
        independent: isRecord(invest)
          ? readInvestCheck(invest.independent, 'story.invest.independent', issues)
          : { status: 'fail', reason: '' },
        negotiable: isRecord(invest)
          ? readInvestCheck(invest.negotiable, 'story.invest.negotiable', issues)
          : { status: 'fail', reason: '' },
        valuable: isRecord(invest)
          ? readInvestCheck(invest.valuable, 'story.invest.valuable', issues)
          : { status: 'fail', reason: '' },
        estimable: isRecord(invest)
          ? readInvestCheck(invest.estimable, 'story.invest.estimable', issues)
          : { status: 'fail', reason: '' },
        small: isRecord(invest)
          ? readInvestCheck(invest.small, 'story.invest.small', issues)
          : { status: 'fail', reason: '' },
        testable: isRecord(invest)
          ? readInvestCheck(invest.testable, 'story.invest.testable', issues)
          : { status: 'fail', reason: '' },
      },
    },
  };

  if (
    !isRecord(dependencies) ||
    (dependencies.independent_story_check !== 'pass' &&
      dependencies.independent_story_check !== 'fail')
  ) {
    issues.push('story.dependencies_and_sequencing.independent_story_check must be pass or fail');
  }
  if (isRecord(invest)) {
    for (const key of INVEST_KEYS) {
      if (!(key in invest)) issues.push(`story.invest.${key} is required`);
    }
  }

  return { story: issues.length === 0 ? story : null, issues, rawYaml };
}

export type CanonicalStoryInvestKey = (typeof INVEST_KEYS)[number];
export const CANONICAL_STORY_INVEST_KEYS = INVEST_KEYS;
