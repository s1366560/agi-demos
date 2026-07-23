import React from 'react';

import { Form, Input, InputNumber, Select, Switch } from 'antd';

import { SECRET_UNCHANGED_SENTINEL } from '@/utils/channelConfigSanitizers';

import type {
  ChannelPluginConfigSchema,
  ChannelPluginSchemaProperty,
} from '@/types/channel';

import type { TFunction } from 'i18next';

export const sanitizePluginConfigValues = (
  values: Record<string, unknown>,
  secretPaths: Set<string>,
  allowedFields?: Set<string>
): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(values).filter(([key, value]) => {
      if (allowedFields && !allowedFields.has(key)) {
        return false;
      }
      if (value === undefined || value === SECRET_UNCHANGED_SENTINEL) {
        return false;
      }
      if (secretPaths.has(key) && value === '') {
        return false;
      }
      return true;
    })
  );

type PluginConfigUiHints = NonNullable<ChannelPluginConfigSchema['config_ui_hints']>;

interface SchemaFormFieldsOptions {
  schemaSupported: boolean;
  properties: Record<string, ChannelPluginSchemaProperty>;
  requiredFields: readonly string[];
  uiHints: PluginConfigUiHints;
  secretPaths: readonly string[];
  /** Fields that must never be rendered (e.g. fields already covered by static form items). */
  excludeFields?: readonly string[] | undefined;
  resolveFormName: (fieldName: string) => string | Array<string | number>;
  /** Extra condition on top of the schema `required` list, e.g. secrets optional when editing. */
  isRequiredField: (sensitive: boolean) => boolean;
  resolveSecretPlaceholder: (placeholder: string | undefined) => string | undefined;
  t: TFunction;
}

const humanizeFieldName = (fieldName: string): string =>
  fieldName
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ');

/**
 * Parameterized schema -> Form.Item renderer shared by the channel config form,
 * the plugin config modal, and the plugin detail page.
 */
export function renderSchemaFormFields({
  schemaSupported,
  properties,
  requiredFields,
  uiHints,
  secretPaths,
  excludeFields,
  resolveFormName,
  isRequiredField,
  resolveSecretPlaceholder,
  t,
}: SchemaFormFieldsOptions): React.ReactNode[] {
  if (!schemaSupported) return [];
  const required = new Set(requiredFields);
  const secrets = new Set(secretPaths);

  return Object.entries(properties)
    .map(([fieldName, schema]) => {
      if (excludeFields?.includes(fieldName)) {
        return null;
      }
      const hint = uiHints[fieldName] || {};
      const sensitive = Boolean(hint.sensitive) || secrets.has(fieldName);
      const requiredField = required.has(fieldName) && isRequiredField(sensitive);
      const formName = resolveFormName(fieldName);
      const label = hint.label || schema.title || humanizeFieldName(fieldName);
      const placeholder = hint.placeholder || schema.description;
      const rules = requiredField
        ? [
            {
              required: true,
              message: t('tenant.pluginHub.configModal.pleaseEnter', { field: label }),
            },
          ]
        : undefined;

      if (schema.type === 'boolean') {
        return (
          <Form.Item key={fieldName} name={formName} label={label} valuePropName="checked">
            <Switch />
          </Form.Item>
        );
      }

      if (schema.enum && schema.enum.length > 0) {
        return (
          <Form.Item
            key={fieldName}
            name={formName}
            label={label}
            {...(rules != null ? { rules } : {})}
          >
            <Select
              aria-label={label}
              options={schema.enum.map((value) => ({
                value,
                label: String(value),
              }))}
            />
          </Form.Item>
        );
      }

      if (schema.type === 'integer' || schema.type === 'number') {
        return (
          <Form.Item
            key={fieldName}
            name={formName}
            label={label}
            {...(rules != null ? { rules } : {})}
          >
            <InputNumber
              style={{ width: '100%' }}
              {...(schema.minimum != null ? { min: schema.minimum } : {})}
              {...(schema.maximum != null ? { max: schema.maximum } : {})}
              placeholder={placeholder}
            />
          </Form.Item>
        );
      }

      return (
        <Form.Item
          key={fieldName}
          name={formName}
          label={label}
          {...(rules != null ? { rules } : {})}
        >
          {sensitive ? (
            <Input.Password placeholder={resolveSecretPlaceholder(placeholder)} />
          ) : (
            <Input placeholder={placeholder} />
          )}
        </Form.Item>
      );
    })
    .filter(Boolean);
}
