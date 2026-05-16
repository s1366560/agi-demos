import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

type NativeBlockType = 'chart' | 'widget';
type NativeBlockTarget = 'backend' | 'frontend_render' | 'frontend_stream' | 'frontend_replay';
type NativeRenderMode = 'chart' | 'json' | 'iframe' | 'image';

interface NativeBlockCaseExpected {
  frontendTabType: 'data' | 'preview';
  renderMode: NativeRenderMode;
  labels?: string[];
  datasetLabels?: string[];
  textContains?: string[];
  imageSrc?: string;
}

export interface NativeBlockFixtureCase {
  id: string;
  blockType: NativeBlockType;
  targets: NativeBlockTarget[];
  description: string;
  title: string;
  updatedTitle?: string;
  content: unknown;
  updatedContent?: unknown;
  expected: NativeBlockCaseExpected;
}

interface NativeBlockFixtures {
  contractVersion: number;
  cases: NativeBlockFixtureCase[];
}

const FIXTURE_PATH = resolve(process.cwd(), '../shared/fixtures/canvas-native-block-fixtures.json');

const nativeBlockFixtures = JSON.parse(readFileSync(FIXTURE_PATH, 'utf8')) as NativeBlockFixtures;

export function getNativeBlockFixtureCase(caseId: string): NativeBlockFixtureCase {
  const fixtureCase = nativeBlockFixtures.cases.find((candidate) => candidate.id === caseId);
  if (!fixtureCase) {
    throw new Error(`Unknown native canvas block fixture: ${caseId}`);
  }
  return fixtureCase;
}

export function getNativeBlockFixtureCases(target?: NativeBlockTarget): NativeBlockFixtureCase[] {
  if (!target) return nativeBlockFixtures.cases;
  return nativeBlockFixtures.cases.filter((fixtureCase) => fixtureCase.targets.includes(target));
}

export function serializeNativeBlockContent(content: unknown): string {
  return typeof content === 'string' ? content : JSON.stringify(content);
}
