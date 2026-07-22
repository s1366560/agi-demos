import { memo, useMemo } from 'react';
import type { CSSProperties } from 'react';

import { useTranslation } from 'react-i18next';

import {
  normalizeStyle,
  resolveBoundNumberValue,
  resolveBoundStringValue,
  type NumberValue,
  type StringValue,
} from './a2uiCustomUtils';
import { useA2UIActions, useA2UIState } from './a2uiInternals';

interface ProgressProperties {
  label?: StringValue | string;
  value?: NumberValue | number;
  max?: NumberValue | number;
  tone?: string;
  showValue?: boolean;
  style?: Record<string, unknown>;
}

type ProgressNode = Record<string, unknown> & {
  id: string;
  dataContextPath?: string;
  weight?: number;
  properties?: ProgressProperties;
};

const PROGRESS_TONES = new Set(['neutral', 'success', 'warning', 'error']);

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export const A2UIProgress = memo(function A2UIProgress({
  node,
  surfaceId,
}: {
  node: ProgressNode;
  surfaceId: string;
}) {
  const actions = useA2UIActions();
  const { version } = useA2UIState();
  const { t } = useTranslation();

  const props = node.properties ?? {};
  const label = useMemo(() => {
    void version;
    return resolveBoundStringValue(props.label, node, surfaceId, actions);
  }, [actions, node, props.label, surfaceId, version]);
  const resolvedValue = useMemo(() => {
    void version;
    return resolveBoundNumberValue(props.value, node, surfaceId, actions) ?? 0;
  }, [actions, node, props.value, surfaceId, version]);
  const resolvedMax = useMemo(() => {
    void version;
    const maxValue = resolveBoundNumberValue(props.max ?? 100, node, surfaceId, actions);
    return typeof maxValue === 'number' && maxValue > 0 ? maxValue : 100;
  }, [actions, node, props.max, surfaceId, version]);
  const toneKey =
    typeof props.tone === 'string' && PROGRESS_TONES.has(props.tone) ? props.tone : 'neutral';
  const clampedValue = clamp(resolvedValue, 0, resolvedMax);
  const percent = resolvedMax > 0 ? clamp((clampedValue / resolvedMax) * 100, 0, 100) : 0;
  const valueText = `${Math.round(percent).toString()}%`;
  const labelText = label ?? t('components.a2uiProgress.progress', { defaultValue: 'Progress' });
  const labelId = `${surfaceId}-${node.id}-progress-label`.replace(/[^a-zA-Z0-9_-]/g, '-');

  const rootStyle =
    node.weight !== undefined ? ({ '--weight': node.weight } as CSSProperties) : undefined;
  const sectionStyle = useMemo(
    () =>
      ({
        display: 'grid',
        gap: '8px',
        minWidth: 0,
        ...normalizeStyle(props.style),
      }) satisfies CSSProperties,
    [props.style]
  );

  return (
    <div className="a2ui-progress" style={rootStyle} data-tone={toneKey}>
      <section className="a2ui-progress__section" style={sectionStyle}>
        {label || props.showValue !== false ? (
          <div className="a2ui-progress__header">
            <span id={labelId} className="a2ui-progress__label" dir="auto">
              {labelText}
            </span>
            {props.showValue !== false ? (
              <span className="a2ui-progress__value">{valueText}</span>
            ) : null}
          </div>
        ) : null}
        <div
          role="progressbar"
          {...(label || props.showValue !== false
            ? { 'aria-labelledby': labelId }
            : {
                'aria-label': t('components.a2uiProgress.progress', { defaultValue: 'Progress' }),
              })}
          aria-valuemin={0}
          aria-valuemax={resolvedMax}
          aria-valuenow={Math.round(clampedValue)}
          aria-valuetext={valueText}
          className="a2ui-progress__track"
        >
          <div
            className="a2ui-progress__fill"
            style={{ transform: `scaleX(${(percent / 100).toString()})` }}
          />
        </div>
      </section>
    </div>
  );
});
