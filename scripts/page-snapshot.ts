#!/usr/bin/env tsx
/**
 * Page snapshot harness — captures a normalized "shape" of each route so
 * regressions in headings, landmarks, and button counts are caught in CI
 * without snapshotting brittle pixel screenshots.
 *
 * Distilled from routa's `page.snapshot.yaml` pattern.
 *
 * Usage:
 *   pnpm tsx scripts/page-snapshot.ts            # update snapshots
 *   pnpm tsx scripts/page-snapshot.ts --check    # exit 1 on diff (CI mode)
 *
 * Configure routes in `ROUTES` below. Snapshots land in
 * `web/src/pages/__snapshots__/<route>.snapshot.yaml`.
 *
 * Requires the dev server to be running on `BASE_URL` (default
 * http://localhost:3000) and a logged-in seed account; auth/login flow is
 * intentionally NOT automated here — use Playwright's storage-state
 * (`PW_STORAGE_STATE`) when available.
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

import { chromium, type Page } from '@playwright/test';
import yaml from 'js-yaml';

interface RouteSpec {
  /** Slug used for the snapshot filename (no slashes). */
  name: string;
  /** Path appended to BASE_URL. */
  path: string;
  /** CSS selector to wait for before snapshotting. */
  ready: string;
}

interface PageShape {
  route: string;
  title: string;
  headings: { level: number; text: string }[];
  landmarks: string[];
  buttons: number;
  links: number;
  inputs: number;
  forms: number;
}

const BASE_URL = process.env.BASE_URL ?? 'http://localhost:3000';
const SNAPSHOT_DIR = path.resolve(__dirname, '..', 'web', 'src', 'pages', '__snapshots__');
const STORAGE_STATE = process.env.PW_STORAGE_STATE;
const CHECK_MODE = process.argv.includes('--check');

const ROUTES: RouteSpec[] = [
  { name: 'login', path: '/login', ready: 'form' },
  { name: 'tenant-overview', path: '/tenant', ready: 'main' },
  { name: 'agent-workspace', path: '/agent', ready: 'main' },
];

async function captureShape(page: Page, route: RouteSpec): Promise<PageShape> {
  await page.goto(`${BASE_URL}${route.path}`, { waitUntil: 'networkidle' });
  await page.waitForSelector(route.ready, { timeout: 10_000 });

  const headings = await page.$$eval('h1, h2, h3, h4, h5, h6', (nodes) =>
    nodes.map((n) => ({
      level: Number(n.tagName.substring(1)),
      text: (n.textContent ?? '').trim().slice(0, 120),
    })),
  );
  const landmarks = await page.$$eval(
    '[role="banner"], [role="main"], [role="navigation"], [role="contentinfo"], [role="complementary"]',
    (nodes) => nodes.map((n) => n.getAttribute('role') ?? n.tagName.toLowerCase()),
  );
  const [buttons, links, inputs, forms] = await Promise.all([
    page.locator('button').count(),
    page.locator('a').count(),
    page.locator('input, textarea, select').count(),
    page.locator('form').count(),
  ]);

  return {
    route: route.path,
    title: await page.title(),
    headings,
    landmarks,
    buttons,
    links,
    inputs,
    forms,
  };
}

async function readExisting(file: string): Promise<string | null> {
  try {
    return await readFile(file, 'utf-8');
  } catch {
    return null;
  }
}

async function main() {
  await mkdir(SNAPSHOT_DIR, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext(
    STORAGE_STATE ? { storageState: STORAGE_STATE } : undefined,
  );
  const page = await context.newPage();

  let drift = 0;
  for (const route of ROUTES) {
    try {
      const shape = await captureShape(page, route);
      const next = `${yaml.dump(shape, { sortKeys: true, lineWidth: 100 })}`;
      const file = path.join(SNAPSHOT_DIR, `${route.name}.snapshot.yaml`);
      const prev = await readExisting(file);

      if (CHECK_MODE) {
        if (prev !== next) {
          drift += 1;
          console.error(`[drift] ${route.name} (${route.path})`);
        } else {
          console.log(`[ok]    ${route.name}`);
        }
      } else {
        await writeFile(file, next, 'utf-8');
        console.log(`[wrote] ${file}`);
      }
    } catch (error) {
      console.error(`[fail]  ${route.name} ${route.path}: ${(error as Error).message}`);
      drift += 1;
    }
  }

  await browser.close();
  if (CHECK_MODE && drift > 0) {
    console.error(`\n${drift} route(s) drifted. Re-run without --check to update.`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
