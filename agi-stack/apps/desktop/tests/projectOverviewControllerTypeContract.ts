import type { ProjectOverviewClient } from '../src/features/project/projectOverviewClient';
import type {
  ProjectOverviewControllerOptions,
} from '../src/features/project/projectOverviewController';

declare const client: ProjectOverviewClient;

const cloudOptions = {
  authority: 'cloud',
  client,
  initialScope: {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  },
} satisfies ProjectOverviewControllerOptions;

const localOptions = {
  authority: 'local',
  client,
  initialScope: {
    authority: 'local',
    tenantId: 'local-tenant',
    projectId: 'local-project',
  },
} satisfies ProjectOverviewControllerOptions;

type ProjectOverviewControllerOptionKey = keyof ProjectOverviewControllerOptions;

// @ts-expect-error Legacy authority-specific clients are no longer accepted.
const legacyCloudClientKey: ProjectOverviewControllerOptionKey = 'cloudClient';

// @ts-expect-error Legacy authority-specific clients are no longer accepted.
const legacyLocalClientKey: ProjectOverviewControllerOptionKey = 'localClient';

void cloudOptions;
void localOptions;
void legacyCloudClientKey;
void legacyLocalClientKey;
