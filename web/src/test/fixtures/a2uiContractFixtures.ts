import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import type { A2UIMessageStreamSnapshot } from '@business/agent/ui/web/stores/agent/a2uiMessages';

type ContractTier = 'tier1' | 'tier2' | 'tier3';
type ContractTarget = 'backend' | 'frontend' | 'prompt';

interface ContractIdentity {
  surfaceId?: string;
  metadataSurfaceId?: string;
  hitlRequestId?: string;
}

interface ContractCase {
  id: string;
  tier: ContractTier;
  targets: ContractTarget[];
  description: string;
  records?: Record<string, unknown>[];
  snapshot?: A2UIMessageStreamSnapshot;
  canonicalizes_to: string | null;
  shouldRender: boolean;
  shouldReject: boolean;
  identity?: ContractIdentity;
  historicalSource?: string;
}

interface ContractFixtures {
  contractVersion: number;
  promptGuidance: {
    supportedComponents: string[];
    componentAliases: Record<string, string>;
    rendererOnlyCompatibility: Record<string, string>;
  };
  cases: ContractCase[];
}

const FIXTURE_PATH = resolve(process.cwd(), '../shared/fixtures/a2ui-contract-fixtures.json');

const contractFixtures = JSON.parse(readFileSync(FIXTURE_PATH, 'utf8')) as ContractFixtures;

export function getA2UIContractFixtures(): ContractFixtures {
  return contractFixtures;
}

export function getA2UIContractCase(caseId: string): ContractCase {
  const contractCase = contractFixtures.cases.find((fixtureCase) => fixtureCase.id === caseId);
  if (!contractCase) {
    throw new Error(`Unknown A2UI contract fixture: ${caseId}`);
  }
  return contractCase;
}

export function getA2UIContractMessages(caseId: string): string {
  const contractCase = getA2UIContractCase(caseId);
  if (!contractCase.records) {
    throw new Error(`A2UI contract fixture ${caseId} does not define message records`);
  }
  return contractCase.records.map((record) => JSON.stringify(record)).join('\n');
}

export function getA2UIContractSnapshot(caseId: string): A2UIMessageStreamSnapshot {
  const contractCase = getA2UIContractCase(caseId);
  if (!contractCase.snapshot) {
    throw new Error(`A2UI contract fixture ${caseId} does not define a snapshot`);
  }
  return structuredClone(contractCase.snapshot);
}
