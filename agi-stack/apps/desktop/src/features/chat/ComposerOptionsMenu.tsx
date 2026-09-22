import { DropdownMenu } from '@radix-ui/themes';
import { MixerHorizontalIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { PickerMenuOption } from './PickerMenu';

/** Secondary composer choices share keyboard navigation and focus restoration. */
export function ComposerOptionsMenu({
  label,
  value,
  options,
  readOnly = false,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly PickerMenuOption[];
  readOnly?: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <button
          className="composer-options-button"
          type="button"
          aria-label={t('composer.toolsLabel')}
          title={t('composer.toolsLabel')}
        >
          <MixerHorizontalIcon aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" side="top" aria-label={t('composer.toolsLabel')}>
        <DropdownMenu.Label>{label}</DropdownMenu.Label>
        <DropdownMenu.RadioGroup value={value} onValueChange={onChange}>
          {options.map((option) => (
            <DropdownMenu.RadioItem
              value={option.value}
              key={option.value}
              disabled={readOnly || option.disabled}
              title={option.description}
            >
              {option.label}
            </DropdownMenu.RadioItem>
          ))}
        </DropdownMenu.RadioGroup>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}
