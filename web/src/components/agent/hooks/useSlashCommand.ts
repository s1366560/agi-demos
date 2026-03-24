import { useState, useCallback, useRef } from 'react';

import type { SkillResponse, SlashItem } from '@/types/agent';

import type { SlashCommandDropdownHandle } from '../SlashCommandDropdown';

interface UseSlashCommandParams {
  onSend: (content: string) => void;
}

interface UseSlashCommandReturn {
  slashDropdownVisible: boolean;
  slashQuery: string;
  slashSelectedIndex: number;
  setSlashSelectedIndex: React.Dispatch<React.SetStateAction<number>>;
  handleSlashSelect: (item: SlashItem) => void;
  /** Process textarea value for slash-command detection. Returns true if slash handled. */
  processSlashInput: (value: string) => boolean;
  /** Handle keyboard events when slash dropdown is visible. Returns true if key was consumed. */
  handleSlashKeyDown: (e: React.KeyboardEvent) => boolean;
  setSlashDropdownVisible: React.Dispatch<React.SetStateAction<boolean>>;
  selectedSkill: SkillResponse | null;
  setSelectedSkill: React.Dispatch<React.SetStateAction<SkillResponse | null>>;
  handleRemoveSkill: () => void;
  slashDropdownRef: React.RefObject<SlashCommandDropdownHandle | null>;
  resetSlash: () => void;
}

export function useSlashCommand({ onSend }: UseSlashCommandParams): UseSlashCommandReturn {
  const [slashDropdownVisible, setSlashDropdownVisible] = useState(false);
  const [slashQuery, setSlashQuery] = useState('');
  const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
  const [selectedSkill, setSelectedSkill] = useState<SkillResponse | null>(null);

  const slashDropdownRef = useRef<SlashCommandDropdownHandle>(null);

  const handleSlashSelect = useCallback(
    (item: SlashItem) => {
      if (item.kind === 'skill') {
        setSelectedSkill(item.data);
        setSlashDropdownVisible(false);
        setSlashQuery('');
      } else {
        setSlashDropdownVisible(false);
        setSlashQuery('');
        const cmdText = `/${item.data.name}`;
        onSend(cmdText);
      }
    },
    [onSend]
  );

  const handleRemoveSkill = useCallback(() => {
    setSelectedSkill(null);
  }, []);

  const processSlashInput = useCallback(
    (value: string): boolean => {
      if (value.startsWith('/') && !selectedSkill) {
        const query = value.slice(1);
        if (!query.includes(' ')) {
          setSlashQuery(query);
          setSlashDropdownVisible(true);
          setSlashSelectedIndex(0);
          return true;
        }
      }

      if (slashDropdownVisible) {
        setSlashDropdownVisible(false);
      }
      return false;
    },
    [selectedSkill, slashDropdownVisible]
  );

  const handleSlashKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!slashDropdownVisible) return false;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSlashSelectedIndex((prev) => prev + 1);
        return true;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSlashSelectedIndex((prev) => Math.max(0, prev - 1));
        return true;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        const item = slashDropdownRef.current?.getSelectedItem();
        if (item) {
          handleSlashSelect(item);
        }
        return true;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setSlashDropdownVisible(false);
        return true;
      }
      return false;
    },
    [slashDropdownVisible, handleSlashSelect]
  );

  const resetSlash = useCallback(() => {
    setSlashDropdownVisible(false);
    setSlashQuery('');
    setSelectedSkill(null);
  }, []);

  return {
    slashDropdownVisible,
    slashQuery,
    slashSelectedIndex,
    setSlashSelectedIndex,
    handleSlashSelect,
    processSlashInput,
    handleSlashKeyDown,
    setSlashDropdownVisible,
    selectedSkill,
    setSelectedSkill,
    handleRemoveSkill,
    slashDropdownRef,
    resetSlash,
  };
}
