import { useState } from 'react';
import { isNpmPackageReference } from './npmPackageReference';

interface Props {
  disabled: boolean;
  labels: { name: string; version: string; preview: string };
  onChange(): void;
  onPreview(name: string, version: string): void;
}

export function NpmPackageSource({ disabled, labels, onChange, onPreview }: Props) {
  const [name, setName] = useState('');
  const [version, setVersion] = useState('');
  return (
    <fieldset disabled={disabled}>
      <legend>npm</legend>
      <label>
        {labels.name}
        <input
          value={name}
          maxLength={214}
          autoCapitalize="none"
          spellCheck={false}
          onChange={(event) => {
            setName(event.target.value);
            onChange();
          }}
        />
      </label>
      <label>
        {labels.version}
        <input
          value={version}
          maxLength={128}
          autoCapitalize="none"
          spellCheck={false}
          onChange={(event) => {
            setVersion(event.target.value);
            onChange();
          }}
        />
      </label>
      <button
        type="button"
        disabled={!isNpmPackageReference(name, version)}
        onClick={() => onPreview(name, version)}
      >
        {labels.preview}
      </button>
    </fieldset>
  );
}
