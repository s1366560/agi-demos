import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import qaConfig from './playwright.config.mjs';

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const evidenceDirectory = mkdtempSync(join(tmpdir(), 'codex-composer-parity-'));
const measurements = [];
const styles = [
  readFileSync(require.resolve('@radix-ui/themes/styles.css'), 'utf8'),
  ...[
    'styles/tokens.css',
    'styles/base.css',
    'styles/chrome.css',
    'features/chat/ChatTimeline.css',
    'features/chat/ChatPanel.css',
    'features/chat/ComposerMenus.css',
    'features/task/NewThreadComposer.css',
  ].map((path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')),
].join('\n');
const script = await esbuild.build({
  stdin: {
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'tsx',
    contents: `
      import React from 'react';
      import {createRoot} from 'react-dom/client';
      import {Theme} from '@radix-ui/themes';
      import {I18nProvider} from './src/i18n';
      import {ToastProvider} from './src/features/feedback/ToastCenter';
      import {ChatPanel} from './src/features/chat/ChatPanel';
      import {NewThreadComposer} from './src/features/task/NewThreadComposer';
      const root = createRoot(document.getElementById('root'));
      const noop = () => {};
      const workspace = {id:'workspace', name:'Desktop Client', tenant_id:'tenant', project_id:'project'};
      const conversation = {id:'thread', tenant_id:'tenant', project_id:'project',workspace_id:null,
        agent_config:{selected_agent_id:'builtin:all-access'},
        execution_selection:{agent_id:null, forced_skill_id:'saved-skill', subagent_id:null}};
      const api = {listWorkspaceAgents:async()=>[],listManagedAgents:async()=>[],
        listManagedSkills:async()=>[{id:'saved-skill',name:'Release review',status:'active'}],
        listManagedSubAgents:async()=>[],listMarketplacePlugins:async()=>[],listPromptTemplates:async()=>[],
        readExecutionSelection:async()=>conversation};
      const model = {value:'model',modelId:'Test model',providerLabel:'Local',roles:[],selected:true};
      window.renderComposers = (appearance) => root.render(<Theme appearance={appearance} accentColor="gray" grayColor="slate">
        <I18nProvider><ToastProvider>
          <section className="comparison-surface idle"><NewThreadComposer workspaceId="workspace" workspace={workspace}
            workspaces={[workspace]} api={api} conversations={[]} mode="work"
            policy={{reasoning_effort:'medium',permission_mode:'automatic'}} modelOptions={[model]}
            canManagePolicy loadingPolicy={false} compatibilityMode={false} disabledReason={null} creating={false} error={null}
            onModeChange={noop} onWorkspaceChange={noop} onCreate={noop} onOpenThread={noop} onManageModels={noop}/></section>
          <section className="comparison-surface active"><div className="desktop-conversation-surface">
            <ChatPanel api={api} conversations={[conversation]} selectedConversationId="thread" messages={[]} timelineState={null}
              agentTaskSignals={[]} sessionTitle="Review" scopeLabel="Project" activityPresence="recorded" activityStructuredEvidence={null}
              composerVariant="session" composerResetKey="compare" initialInput="" sending={false} disabledReason={null}
              activeWorkflowTarget="conversation" runInputDelivery={null} runInputDeliveryOptions={[]} runInputs={[]}
              runInputsLoading={false} runInputsError={null} promotingRunInputId={null} runInputAuthorityRunId={null}
              references={[]} onRunInputDeliveryChange={noop} onPromoteRunInput={noop} onRemoveReference={noop}
              onSend={noop} onRefresh={noop} onLoadEarlier={noop} onRespondToHitl={async()=>{}} respondableHitlRequestIds={[]}
              onWorkflowSelect={noop} imagePreviewClient={null} permissionPreset="full" permissionPresetFullAccessAcknowledged
              onPermissionPresetChange={noop} onAcknowledgeFullAccessWarning={noop} onOpenCommands={noop}
              desktopRuntimeConfig={{mode:'local', apiBaseUrl:'http://localhost',apiKey:'',localApiToken:'',
                tenantId:'tenant',projectId:'project',workspaceId:'',workspaceRoot:'',deviceAuthorizationBaseUrl:''}}
              modelLabel="Test model" modelOptions={[model]} selectedModelValue="model" onModelChange={async()=>{}}/>
          </div></section>
        </ToastProvider></I18nProvider></Theme>);
    `,
  },
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'iife',
  loader: { '.css': 'empty', '.svg': 'text' },
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.PROD': 'true' },
});
let browser;
before(async () => {
  browser = await chromium.launch({ headless: true, ...qaConfig.use.launchOptions });
});
after(async () => {
  await browser?.close();
  writeFileSync(
    join(evidenceDirectory, 'measurements.json'),
    JSON.stringify(measurements, null, 2),
  );
  console.log(`Composer comparison evidence: ${evidenceDirectory}`);
});
for (const width of [1100, 1440])
  for (const theme of ['light', 'dark']) {
    test(`real idle and in-conversation composers share card anatomy: ${width}-${theme}`, async () => {
      const page = await browser.newPage({
        viewport: { width, height: 1024 },
        colorScheme: theme,
        reducedMotion: 'reduce',
      });
      page.on('pageerror', (error) => console.log('Fixture error:', error.message));
      try {
        await page.route('http://composer.test/', (route) =>
          route.fulfill({ contentType: 'text/html', body: '<div></div>' }),
        );
        await page.goto('http://composer.test/');
        await page.setContent(`<html data-theme="${theme}"><head><style>${styles}
        .comparison-surface { width:min(900px,100%);margin-inline:auto; }
        .comparison-surface.idle { height:330px; }
        .comparison-surface .new-thread-view { min-height:0;height:100%; }
        .comparison-surface.active { height:620px; }
        .comparison-surface.active .chat-shell { min-height:0;height:100%; }
      </style></head><body><div id="root"></div></body></html>`);
        await page.addScriptTag({ content: script.outputFiles[0].text });
        await page.evaluate((appearance) => window.renderComposers(appearance), theme);
        await page.locator('.active .composer-context-chips button').waitFor({ timeout: 5000 });
        const metrics = await page.evaluate(() => {
          const measure = (selector) => {
            const element = document.querySelector(selector),
              style = getComputedStyle(element),
              rect = element.getBoundingClientRect();
            return {
              width: rect.width,
              height: rect.height,
              background: style.backgroundColor,
              radius: style.borderRadius,
              padding: style.padding,
              fontSize: style.fontSize,
              borderTop: style.borderTopWidth,
            };
          };
          return {
            idle: measure('.new-thread-composer'),
            active: measure('.session-composer-editor'),
            idleInput: measure('.new-thread-composer textarea'),
            activeInput: measure('.session-composer-editor textarea'),
            idleFooter: measure('.new-thread-composer-toolbar'),
            activeFooter: measure('.chat-composer-footer'),
            idleSend: measure('.new-thread-view .send-button'),
            activeSend: measure('.active .send-pill'),
            chip: measure('.active .composer-context-chips'),
            chipButton: measure('.active .composer-context-chips button'),
            overflow: document.documentElement.scrollWidth - innerWidth,
          };
        });
        measurements.push({ width, theme, ...metrics });
        assert.equal(metrics.idle.width, metrics.active.width);
        assert.equal(metrics.idle.radius, metrics.active.radius);
        assert.equal(metrics.idle.background, metrics.active.background);
        for (const key of ['height', 'padding', 'fontSize'])
          assert.equal(metrics.idleInput[key], metrics.activeInput[key], key);
        assert.equal(metrics.idleFooter.padding, metrics.activeFooter.padding);
        assert.equal(metrics.activeFooter.borderTop, '0px');
        assert.equal(metrics.idleSend.width, metrics.activeSend.width);
        assert.equal(metrics.idleSend.height, metrics.activeSend.height);
        assert.equal(metrics.idleSend.radius, metrics.activeSend.radius);
        assert.ok(metrics.chip.height <= 42, 'selected context occupies a compact row');
        assert.ok(metrics.chipButton.height <= 34, 'chip does not stretch');
        assert.equal(metrics.overflow, 0);
        await page.screenshot({ path: join(evidenceDirectory, `${width}-${theme}.png`) });
      } catch (error) {
        console.log(await page.locator('body').innerText());
        throw error;
      } finally {
        await page.close();
      }
    });
  }
