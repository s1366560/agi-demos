import {
  BellIcon,
  ComponentInstanceIcon,
  CubeIcon,
  FontStyleIcon,
  GearIcon,
  IdCardIcon,
  MagicWandIcon,
  PersonIcon,
} from '@radix-ui/react-icons';

import type { SettingsSection } from './settingsNavigationModel';

export const settingsSectionMeta = {
  account: {
    label: 'settings.account',
    description: 'settings.accountDescription',
    Icon: IdCardIcon,
  },
  workspace: {
    label: 'settings.workspace',
    description: 'settings.workspaceDescription',
    Icon: CubeIcon,
  },
  general: {
    label: 'settings.general',
    description: 'settings.generalDescription',
    Icon: GearIcon,
  },
  connection: {
    label: 'settings.connectionRecovery',
    description: 'settings.connectionRecoveryDescription',
    Icon: GearIcon,
  },
  appearance: {
    label: 'settings.appearance',
    description: 'settings.appearanceDescription',
    Icon: FontStyleIcon,
  },
  notifications: {
    label: 'settings.notifications',
    description: 'settings.notificationsDescription',
    Icon: BellIcon,
  },
  models: {
    label: 'settings.models',
    description: 'settings.modelsDescription',
    Icon: CubeIcon,
  },
  skills: {
    label: 'settings.skills',
    description: 'settings.skillsDescription',
    Icon: MagicWandIcon,
  },
  plugins: {
    label: 'settings.plugins',
    description: 'settings.pluginsDescription',
    Icon: ComponentInstanceIcon,
  },
  agents: {
    label: 'settings.agents',
    description: 'settings.agentsDescription',
    Icon: PersonIcon,
  },
  subagents: {
    label: 'settings.subagents',
    description: 'settings.subagentsDescription',
    Icon: PersonIcon,
  },
} satisfies Record<
  SettingsSection,
  { label: string; description: string; Icon: typeof GearIcon }
>;
