import { useMemo, useState, type ReactNode } from 'react';
import {
  CheckCircledIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CrossCircledIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  CanonicalStoryDocument,
  CanonicalStoryInvestCheck,
  CanonicalStoryInvestKey,
  CanonicalStoryParseResult,
  CanonicalStoryStatus,
} from './canonicalStoryModel';
import { CANONICAL_STORY_INVEST_KEYS } from './canonicalStoryModel';
import { CodeBlockFrame } from './HighlightedCode';
import './CanonicalStoryCard.css';

const INVEST_LABELS: Record<CanonicalStoryInvestKey, string> = {
  independent: 'I',
  negotiable: 'N',
  valuable: 'V',
  estimable: 'E',
  small: 'S',
  testable: 'T',
};

function StatusIcon({ status }: { status: CanonicalStoryStatus }) {
  if (status === 'pass') return <CheckCircledIcon aria-hidden="true" />;
  if (status === 'warning') return <ExclamationTriangleIcon aria-hidden="true" />;
  return <CrossCircledIcon aria-hidden="true" />;
}

function InvestBadge({
  name,
  check,
}: {
  name: CanonicalStoryInvestKey;
  check: CanonicalStoryInvestCheck;
}) {
  const { t } = useI18n();
  const statusLabel = t(`chat.canonicalStory.status.${check.status}`);
  return (
    <span
      className={`canonical-story-invest is-${check.status}`}
      title={`${name}: ${check.reason || statusLabel}`}
    >
      <span aria-hidden="true">{INVEST_LABELS[name]}</span>
      <StatusIcon status={check.status} />
      <span className="sr-only">{`${name}: ${statusLabel}`}</span>
    </span>
  );
}

function StorySection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="canonical-story-section">
      <h4>{label}</h4>
      <div>{children}</div>
    </section>
  );
}

function StoryStringList({ items }: { items: readonly string[] }) {
  const { t } = useI18n();
  if (items.length === 0) {
    return <span className="canonical-story-empty">{t('chat.canonicalStory.none')}</span>;
  }
  return (
    <ul>
      {items.map((item, index) => (
        <li key={`${String(index)}-${item}`}>{item}</li>
      ))}
    </ul>
  );
}

function ParsedCanonicalStory({
  story,
}: {
  story: CanonicalStoryDocument['story'];
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const investEntries = useMemo(
    () =>
      CANONICAL_STORY_INVEST_KEYS.map((name) => ({
        name,
        check: story.invest[name],
      })),
    [story.invest],
  );
  const issueCount = investEntries.filter(({ check }) => check.status !== 'pass').length;
  const independent = story.dependencies_and_sequencing.independent_story_check === 'pass';

  return (
    <div className="canonical-story-card" data-testid="canonical-story-card">
      <button
        className="canonical-story-toggle"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="canonical-story-disclosure" aria-hidden="true">
          {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </span>
        <span className="canonical-story-heading">
          <span className="canonical-story-eyebrow">
            {t('chat.canonicalStory.story')} · v{String(story.version)}
            {!independent ? (
              <span className="canonical-story-dependency-warning">
                <ExclamationTriangleIcon aria-hidden="true" />
                {t('chat.canonicalStory.dependsOnOthers')}
              </span>
            ) : null}
          </span>
          <strong title={story.title}>{story.title}</strong>
          <span className="canonical-story-summary">
            <span className="canonical-story-invest-list" aria-label="INVEST">
              {investEntries.map(({ name, check }) => (
                <InvestBadge key={name} name={name} check={check} />
              ))}
            </span>
            <span>
              {t('chat.canonicalStory.acceptanceCount', {
                count: story.acceptance_criteria.length,
              })}
              {issueCount > 0
                ? ` · ${t('chat.canonicalStory.investIssueCount', { count: issueCount })}`
                : ''}
            </span>
          </span>
        </span>
      </button>

      {open ? (
        <div className="canonical-story-details">
          <StorySection label={t('chat.canonicalStory.problem')}>
            <p>{story.problem_statement}</p>
          </StorySection>
          <StorySection label={t('chat.canonicalStory.userValue')}>
            <p>{story.user_value}</p>
          </StorySection>
          <StorySection label={t('chat.canonicalStory.acceptanceCriteria')}>
            <ol className="canonical-story-criteria">
              {story.acceptance_criteria.map((criterion, index) => (
                <li key={`${criterion.id}-${String(index)}`}>
                  <code>{criterion.id}</code>
                  <span>{criterion.text}</span>
                  <small className={criterion.testable ? 'is-pass' : 'is-fail'}>
                    {t(
                      criterion.testable
                        ? 'chat.canonicalStory.testable'
                        : 'chat.canonicalStory.untestable',
                    )}
                  </small>
                </li>
              ))}
            </ol>
          </StorySection>
          <StorySection label={t('chat.canonicalStory.constraints')}>
            <StoryStringList items={story.constraints_and_affected_areas} />
          </StorySection>
          <StorySection label={t('chat.canonicalStory.dependencies')}>
            <dl className="canonical-story-dependencies">
              <div>
                <dt>{t('chat.canonicalStory.independentCheck')}</dt>
                <dd className={independent ? 'is-pass' : 'is-fail'}>
                  {story.dependencies_and_sequencing.independent_story_check}
                </dd>
              </div>
              <div>
                <dt>{t('chat.canonicalStory.dependsOn')}</dt>
                <dd>
                  {story.dependencies_and_sequencing.depends_on.join(', ') ||
                    t('chat.canonicalStory.none')}
                </dd>
              </div>
              <div>
                <dt>{t('chat.canonicalStory.unblockWhen')}</dt>
                <dd>{story.dependencies_and_sequencing.unblock_condition}</dd>
              </div>
            </dl>
          </StorySection>
          {story.out_of_scope.length > 0 ? (
            <StorySection label={t('chat.canonicalStory.outOfScope')}>
              <StoryStringList items={story.out_of_scope} />
            </StorySection>
          ) : null}
          <StorySection label="INVEST">
            <ul className="canonical-story-invest-details">
              {investEntries.map(({ name, check }) => (
                <li key={name}>
                  <InvestBadge name={name} check={check} />
                  <strong>{name}</strong>
                  <span>{check.reason}</span>
                </li>
              ))}
            </ul>
          </StorySection>
        </div>
      ) : null}
    </div>
  );
}

function canonicalStoryIssueLabel(
  issue: string,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  const [code, value = '', limit = ''] = issue.split(':');
  if (code === 'parse_error') return t('chat.canonicalStory.issue.parseError');
  if (code === 'aliases_forbidden') return t('chat.canonicalStory.issue.aliasesForbidden');
  if (code === 'source_too_long') {
    return t('chat.canonicalStory.issue.sourceTooLong', { limit: value });
  }
  if (code === 'value_limit') {
    return t('chat.canonicalStory.issue.valueLimit', { limit: value });
  }
  if (code === 'depth_limit') {
    return t('chat.canonicalStory.issue.depthLimit', { limit: value });
  }
  if (code === 'string_too_long') {
    return t('chat.canonicalStory.issue.stringTooLong', { path: value, limit });
  }
  if (code === 'collection_limit') {
    return t('chat.canonicalStory.issue.collectionLimit', { path: value, limit });
  }
  if (code === 'field_limit') {
    return t('chat.canonicalStory.issue.fieldLimit', { path: value, limit });
  }
  if (code === 'prohibited_field') {
    return t('chat.canonicalStory.issue.prohibitedField', { path: value });
  }
  if (code === 'positive_integer_required') {
    return t('chat.canonicalStory.issue.positiveInteger', { path: value });
  }
  if (code === 'string_required') {
    return t('chat.canonicalStory.issue.stringRequired', { path: value });
  }
  if (code === 'boolean_required') {
    return t('chat.canonicalStory.issue.booleanRequired', { path: value });
  }
  if (code === 'string_array_required') {
    return t('chat.canonicalStory.issue.stringArrayRequired', { path: value });
  }
  if (code === 'item_required') {
    return t('chat.canonicalStory.issue.itemRequired', { path: value });
  }
  if (code === 'array_required') {
    return t('chat.canonicalStory.issue.arrayRequired', { path: value });
  }
  if (code === 'minimum_items') {
    return t('chat.canonicalStory.issue.minimumItems', { path: value, limit });
  }
  if (code === 'acceptance_ids_not_unique') {
    return t('chat.canonicalStory.issue.uniqueAcceptanceIds');
  }
  if (code === 'object_required') {
    return t('chat.canonicalStory.issue.objectRequired', { path: value });
  }
  if (code === 'pass_fail_required') {
    return t('chat.canonicalStory.issue.passFailRequired', { path: value });
  }
  if (code === 'story_status_required') {
    return t('chat.canonicalStory.issue.storyStatusRequired', { path: value });
  }
  return t('chat.canonicalStory.issue.invalid');
}

function InvalidCanonicalStory({ result }: { result: CanonicalStoryParseResult }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="canonical-story-card is-invalid" data-testid="canonical-story-invalid">
      <button
        className="canonical-story-toggle"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="canonical-story-disclosure" aria-hidden="true">
          {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </span>
        <ExclamationTriangleIcon aria-hidden="true" />
        <strong>
          {t('chat.canonicalStory.invalidIssueCount', { count: result.issues.length })}
        </strong>
      </button>
      {open ? (
        <div className="canonical-story-invalid-details">
          <ul>
            {result.issues.map((issue, index) => (
              <li key={`${String(index)}-${issue}`}>{canonicalStoryIssueLabel(issue, t)}</li>
            ))}
          </ul>
          <CodeBlockFrame code={result.rawYaml} language="canonical-story" />
        </div>
      ) : null}
    </div>
  );
}

export function CanonicalStoryCard({ result }: { result: CanonicalStoryParseResult }) {
  if (!result.story) return <InvalidCanonicalStory result={result} />;
  return <ParsedCanonicalStory story={result.story.story} />;
}
