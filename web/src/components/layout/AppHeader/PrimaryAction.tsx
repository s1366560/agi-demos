/**
 * AppHeader.PrimaryAction - Compound Component
 *
 * Primary action button with optional icon.
 */

import * as React from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

export interface PrimaryActionProps {
  label: string;
  to: string;
  icon?: React.ReactNode;
  variant?: 'primary' | 'secondary';
}

export const PrimaryAction = React.memo(function PrimaryAction({
  label,
  to,
  icon,
  variant = 'primary',
}: PrimaryActionProps) {
  const { t } = useTranslation();

  const translateLabel = (key: string) => {
    return key.includes('.') ? t(key) : key;
  };

  const buttonClass = variant === 'primary' ? 'btn-primary' : 'btn-secondary';

  return (
    <Link to={to}>
      <button className={buttonClass}>
        {icon}
        <span>{translateLabel(label)}</span>
      </button>
    </Link>
  );
});

PrimaryAction.displayName = 'AppHeader.PrimaryAction';
