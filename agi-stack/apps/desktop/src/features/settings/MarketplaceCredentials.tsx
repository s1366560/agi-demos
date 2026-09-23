import { useState } from 'react';
import type { MarketplaceInstallation } from '../../../../../packages/plugin-marketplace-ui/src/client';
import type { MarketplaceMessage } from '../../../../../packages/plugin-marketplace-ui/src/messages';

type Props = {
  installation: MarketplaceInstallation;
  t: (key: MarketplaceMessage) => string;
  busy: boolean;
  canManage: boolean;
  onSave: (credentials: Record<string, string>) => Promise<void>;
  onCancel: () => void;
};
export function MarketplaceCredentials({
  installation,
  t,
  busy,
  canManage,
  onSave,
  onCancel,
}: Props) {
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  const [values, setValues] = useState<Record<string, string>>({});
  const required = installation.required_credentials;
  return (
    <form
      className="marketplace-review"
      onSubmit={(event) => {
        event.preventDefault();
        const credentials = required?.length ? values : { [name]: value };
        void onSave(credentials).finally(() => {
          setValue('');
          setValues({});
        });
      }}
    >
      <h3>
        {t('configure')}: {installation.name}
      </h3>
      <p>{t('credentialHint')}</p>
      {required?.length ? (
        required.map((key) => (
          <label key={key}>
            {key}
            <input
              required
              type="password"
              autoComplete="new-password"
              value={values[key] ?? ''}
              onChange={(event) =>
                setValues({ ...values, [key]: event.target.value })
              }
            />
          </label>
        ))
      ) : (
        <>
          <label>
            {t('secretName')}
            <input
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            {t('secretValue')}
            <input
              required
              type="password"
              autoComplete="new-password"
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
        </>
      )}
      <button type="submit" disabled={busy || !canManage}>
        {t('save')}
      </button>
      <button type="button" disabled={busy} onClick={onCancel}>
        {t('cancel')}
      </button>
    </form>
  );
}
