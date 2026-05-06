import { describe, expect, it } from 'vitest';

import { isStoryReadyToAdvance, parseCanonicalStory } from '@/utils/canonicalStory';

const GOOD_STORY = `
Some prose above.

\`\`\`yaml
story:
  version: 1
  language: en
  title: Add SSO login
  problem_statement: Users need single sign-on
  user_value: Faster login, fewer passwords
  acceptance_criteria:
    - id: AC-1
      text: User can log in via Okta
      testable: true
  constraints_and_affected_areas:
    - auth-service
  dependencies_and_sequencing:
    independent_story_check: pass
    depends_on: []
    unblock_condition: ""
  out_of_scope:
    - migration of legacy accounts
  invest:
    independent: { status: pass, reason: "no upstream blockers" }
    negotiable:  { status: pass, reason: "scope can shrink" }
    valuable:    { status: pass, reason: "high user demand" }
    estimable:   { status: pass, reason: "well-understood" }
    small:       { status: pass, reason: "<5 days" }
    testable:    { status: pass, reason: "Okta sandbox available" }
\`\`\`

More prose below.
`;

describe('parseCanonicalStory', () => {
  it('returns empty result when no yaml block is present', () => {
    const result = parseCanonicalStory('just plain text');
    expect(result.hasYamlBlock).toBe(false);
    expect(result.story).toBeNull();
    expect(result.issues).toHaveLength(0);
  });

  it('returns null when input is empty/null', () => {
    expect(parseCanonicalStory(null).hasYamlBlock).toBe(false);
    expect(parseCanonicalStory('').hasYamlBlock).toBe(false);
  });

  it('parses a well-formed story', () => {
    const result = parseCanonicalStory(GOOD_STORY);
    expect(result.hasYamlBlock).toBe(true);
    expect(result.issues).toEqual([]);
    expect(result.story?.story.title).toBe('Add SSO login');
    expect(result.story?.story.acceptance_criteria).toHaveLength(1);
    expect(result.story?.story.invest.independent.status).toBe('pass');
  });

  it('reports issues when required fields are missing', () => {
    const bad = `
\`\`\`yaml
story:
  version: 1
\`\`\`
`;
    const result = parseCanonicalStory(bad);
    expect(result.hasYamlBlock).toBe(true);
    expect(result.story).toBeNull();
    expect(result.issues.length).toBeGreaterThan(0);
    expect(result.issues.some((m) => m.includes('story.title'))).toBe(true);
  });

  it('flags yaml syntax errors', () => {
    const bad = '```yaml\nstory: [unbalanced\n```';
    const result = parseCanonicalStory(bad);
    expect(result.hasYamlBlock).toBe(true);
    expect(result.story).toBeNull();
    expect(result.issues[0]).toMatch(/yaml syntax error/);
  });

  it('rejects empty acceptance_criteria', () => {
    const bad = `
\`\`\`yaml
story:
  version: 1
  language: en
  title: x
  problem_statement: x
  user_value: x
  acceptance_criteria: []
  dependencies_and_sequencing:
    independent_story_check: pass
    depends_on: []
    unblock_condition: ""
  invest:
    independent: { status: pass, reason: x }
    negotiable: { status: pass, reason: x }
    valuable: { status: pass, reason: x }
    estimable: { status: pass, reason: x }
    small: { status: pass, reason: x }
    testable: { status: pass, reason: x }
\`\`\`
`;
    const result = parseCanonicalStory(bad);
    expect(result.story).toBeNull();
    expect(result.issues.some((m) => m.includes('acceptance_criteria'))).toBe(true);
  });
});

describe('isStoryReadyToAdvance', () => {
  it('returns true when story is parsed and all INVEST checks pass', () => {
    const result = parseCanonicalStory(GOOD_STORY);
    expect(isStoryReadyToAdvance(result)).toBe(true);
  });

  it('returns false when any INVEST check is not pass', () => {
    const story = parseCanonicalStory(GOOD_STORY).story!;
    story.story.invest.small = { status: 'warning', reason: 'borderline' };
    expect(
      isStoryReadyToAdvance({
        hasYamlBlock: true,
        story,
        issues: [],
        rawYaml: '',
      }),
    ).toBe(false);
  });
});
