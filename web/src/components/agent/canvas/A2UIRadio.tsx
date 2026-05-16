import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties, ChangeEvent } from 'react';

import {
  normalizeStyle,
  resolveBindingPath,
  resolveBoundStringValue,
  type StringValue,
} from './a2uiCustomUtils';
import { useA2UIActions, useA2UIState } from './a2uiInternals';

interface RadioOption {
  label?: StringValue | string;
  text?: StringValue | string;
  value?: string | number | boolean;
}

interface RadioProperties {
  description?: StringValue | string;
  options?: RadioOption[];
  value?: StringValue | string;
  selection?: StringValue | string;
  selections?: { path?: string };
  selected?: StringValue | string;
  path?: string;
  style?: Record<string, unknown>;
}

type RadioNode = Record<string, unknown> & {
  id: string;
  dataContextPath?: string;
  weight?: number;
  properties?: RadioProperties;
};

interface ResolvedRadioOption {
  label: string;
  value: string;
}

function resolveDisplayString(
  input: unknown,
  node: RadioNode,
  surfaceId: string,
  actions: ReturnType<typeof useA2UIActions>
): string | undefined {
  return resolveBoundStringValue(input, node, surfaceId, actions);
}

function normalizeRadioOptions(
  input: unknown,
  node: RadioNode,
  surfaceId: string,
  actions: ReturnType<typeof useA2UIActions>
): ResolvedRadioOption[] {
  if (!Array.isArray(input)) {
    return [];
  }

  return input.flatMap((option) => {
    if (typeof option === 'string' && option.trim().length > 0) {
      return [{ label: option, value: option }];
    }
    if (!option || typeof option !== 'object' || Array.isArray(option)) {
      return [];
    }

    const record = option as RadioOption;
    const rawValue = record.value;
    const value =
      typeof rawValue === 'string' && rawValue.trim().length > 0
        ? rawValue
        : typeof rawValue === 'number' || typeof rawValue === 'boolean'
          ? String(rawValue)
          : undefined;
    if (!value) {
      return [];
    }

    const label = resolveDisplayString(
      record.label ?? record.text ?? value,
      node,
      surfaceId,
      actions
    );
    if (!label) {
      return [];
    }
    return [{ label, value }];
  });
}

export const A2UIRadio = memo(function A2UIRadio({
  node,
  surfaceId,
}: {
  node: RadioNode;
  surfaceId: string;
}) {
  const actions = useA2UIActions();
  const { version } = useA2UIState();

  const props = node.properties ?? {};
  const bindingInput = useMemo(
    () =>
      props.value ??
      props.selection ??
      props.selected ??
      props.selections ??
      (props.path ? { path: props.path } : undefined),
    [props.path, props.selected, props.selection, props.selections, props.value]
  );
  const description = useMemo(() => {
    void version;
    return resolveDisplayString(props.description, node, surfaceId, actions);
  }, [actions, node, props.description, surfaceId, version]);
  const options = useMemo(() => {
    void version;
    return normalizeRadioOptions(props.options, node, surfaceId, actions);
  }, [actions, node, props.options, surfaceId, version]);
  const boundPath = useMemo(
    () => resolveBindingPath(bindingInput, node, actions),
    [actions, bindingInput, node]
  );
  const resolvedValue = useMemo(() => {
    void version;
    return resolveBoundStringValue(bindingInput, node, surfaceId, actions);
  }, [actions, bindingInput, node, surfaceId, version]);
  const [localValue, setLocalValue] = useState<string | undefined>(resolvedValue);

  useEffect(() => {
    setLocalValue(resolvedValue);
  }, [resolvedValue]);

  const descriptionId = useMemo(
    () =>
      description
        ? `${surfaceId}-${node.id}-description`.replace(/[^a-zA-Z0-9_-]/g, '-')
        : undefined,
    [description, node.id, surfaceId]
  );

  const handleChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const nextValue = event.target.value;
      setLocalValue(nextValue);
      if (boundPath) {
        actions.setData(node, boundPath, nextValue, surfaceId);
      }
    },
    [actions, boundPath, node, surfaceId]
  );

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

  if (options.length === 0) {
    return null;
  }

  return (
    <div className="a2ui-radio" style={rootStyle}>
      <section className="a2ui-radio__section" style={sectionStyle}>
        {description ? (
          <div id={descriptionId} className="a2ui-radio__description" dir="auto">
            {description}
          </div>
        ) : null}
        <div
          role="radiogroup"
          {...(descriptionId
            ? { 'aria-labelledby': descriptionId }
            : { 'aria-label': 'Selection options' })}
          className="a2ui-radio__group"
        >
          {options.map((option) => (
            <label key={option.value} className="a2ui-radio__option">
              <input
                type="radio"
                name={`${surfaceId}-${node.id}`}
                value={option.value}
                checked={localValue === option.value}
                onChange={handleChange}
                className="a2ui-radio__input"
              />
              <span className="a2ui-radio__label" dir="auto">
                {option.label}
              </span>
            </label>
          ))}
        </div>
      </section>
    </div>
  );
});
