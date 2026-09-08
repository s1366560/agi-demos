import { devNull } from 'node:os';

// Git hooks export repository/index state. cwd alone cannot select another repo.
// Remove all Git overrides, including numbered config entries and future additions.
export function isolatedGitEnvironment(environment = process.env) {
  return {
    ...Object.fromEntries(
      Object.entries(environment).filter(([key]) => !key.toUpperCase().startsWith('GIT_'))
    ),
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_CONFIG_GLOBAL: devNull,
    GIT_CONFIG_SYSTEM: devNull,
  };
}
