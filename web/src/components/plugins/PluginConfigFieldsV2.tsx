import { useState } from 'react';

import { useTranslation } from 'react-i18next';

interface Props {
  readonly schema: Readonly<Record<string, unknown>>;
  readonly value: unknown;
  readonly name: string;
  readonly onChange: (value: unknown) => void;
  readonly onValidity: (path: string, valid: boolean) => void;
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** Ordinary public configuration only. Credential fields use their existing vault UI. */
export function PluginConfigFieldsV2({ schema, value, name, onChange, onValidity }: Props) {
  const { t } = useTranslation();
  const label = typeof schema.title === 'string' ? schema.title : name;
  const hint = typeof schema.description === 'string' ? schema.description : undefined;
  if (record(schema.properties)) {
    const values = record(value) ? value : {};
    return (
      <fieldset className="space-y-3">
        {name ? <legend>{label}</legend> : null}
        {Object.entries(schema.properties).map(([key, child]) =>
          record(child) ? (
            <PluginConfigFieldsV2
              key={key}
              schema={child}
              value={values[key]}
              name={name ? `${name}.${key}` : key}
              onChange={(next) => {
                onChange({ ...values, [key]: next });
              }}
              onValidity={onValidity}
            />
          ) : null
        )}
      </fieldset>
    );
  }
  if (Object.hasOwn(schema, 'const')) {
    return (
      <p>
        {label}: <code>{JSON.stringify(schema.const)}</code>
      </p>
    );
  }
  if (Array.isArray(schema.enum)) {
    return (
      <label className="flex flex-col gap-1">
        {label}
        <select
          aria-label={label}
          value={value === undefined ? '' : JSON.stringify(value)}
          onChange={(event) => {
            onChange(JSON.parse(event.target.value));
          }}
        >
          <option value="" disabled>
            {t('plugins.chooseValue')}
          </option>
          {schema.enum.map((option, index) => (
            <option key={index} value={JSON.stringify(option)}>
              {String(option)}
            </option>
          ))}
        </select>
        {hint ? <small>{hint}</small> : null}
      </label>
    );
  }
  if (schema.type === 'boolean') {
    return (
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(event) => {
            onChange(event.target.checked);
          }}
        />
        {label}
      </label>
    );
  }
  if (schema.type === 'integer' || schema.type === 'number') {
    return (
      <label className="flex flex-col gap-1">
        {label}
        <input
          type="number"
          value={typeof value === 'number' ? value : ''}
          step={schema.type === 'integer' ? 1 : 'any'}
          min={typeof schema.minimum === 'number' ? schema.minimum : undefined}
          max={typeof schema.maximum === 'number' ? schema.maximum : undefined}
          onChange={(event) => {
            const next = event.target.valueAsNumber;
            const valid =
              Number.isFinite(next) && (schema.type !== 'integer' || Number.isInteger(next));
            onValidity(name, valid);
            if (valid) onChange(next);
          }}
        />
        {hint ? <small>{hint}</small> : null}
      </label>
    );
  }
  if (schema.type === 'string') {
    return (
      <label className="flex flex-col gap-1">
        {label}
        <input
          value={typeof value === 'string' ? value : ''}
          minLength={typeof schema.minLength === 'number' ? schema.minLength : undefined}
          maxLength={typeof schema.maxLength === 'number' ? schema.maxLength : undefined}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
        {hint ? <small>{hint}</small> : null}
      </label>
    );
  }
  return <JsonConfigField name={label} value={value} onChange={onChange} onValidity={onValidity} />;
}

function JsonConfigField({ name, value, onChange, onValidity }: Omit<Props, 'schema'>) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(() => JSON.stringify(value ?? null, null, 2));
  const [invalid, setInvalid] = useState(false);
  return (
    <label className="flex flex-col gap-1">
      {name || t('plugins.configuration')}
      <textarea
        aria-label={name || t('plugins.configuration')}
        rows={5}
        value={draft}
        aria-invalid={invalid}
        onChange={(event) => {
          setDraft(event.target.value);
          try {
            const parsed: unknown = JSON.parse(event.target.value);
            setInvalid(false);
            onValidity(name, true);
            onChange(parsed);
          } catch {
            setInvalid(true);
            onValidity(name, false);
          }
        }}
      />
      {invalid ? <span role="alert">{t('plugins.invalidJson')}</span> : null}
    </label>
  );
}
