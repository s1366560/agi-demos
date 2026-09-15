import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const {
  groupSubAgentTimelineItems,
} = require("/tmp/agistack-desktop-test-dist/src/features/chat/subagentTimelineGroupModel.js");

const event = (id, type, payload = {}) => ({
  id,
  type,
  payload: { subagent_id: "reviewer", ...payload },
});

test("a completed local SubAgent event cannot consume the next active invocation", () => {
  const result = groupSubAgentTimelineItems([
    event("previous-end", "subagent_completed", { success: true }),
    event("next-start", "subagent_started"),
  ]);

  assert.deepEqual(
    result.groups.map(({ itemIds, status }) => ({ itemIds, status })),
    [
      { itemIds: ["previous-end"], status: "success" },
      { itemIds: ["next-start"], status: "running" },
    ],
  );
});

test("interleaved parent work leaves no orphan running SubAgent progress group", () => {
  const result = groupSubAgentTimelineItems([
    event("start", "subagent_started"),
    { id: "parent-tool", type: "tool_started", payload: {} },
    event("progress", "subagent_session_update", { progress: 0.5 }),
    event("other-start", "subagent_started", { subagent_id: "other-reviewer" }),
    event("end", "subagent_completed", { success: true }),
  ]);

  assert.deepEqual(
    result.groups.map(({ itemIds, status }) => ({ itemIds, status })),
    [
      { itemIds: ["start", "progress", "end"], status: "success" },
      { itemIds: ["other-start"], status: "running" },
    ],
  );
  assert.deepEqual(result.claimedItemIds, [
    "start",
    "progress",
    "other-start",
    "end",
  ]);
  assert.equal(result.groups[0].phases.executing, true);
});

test('actual cancellation timeline coalesces killed and ended only for the exact execution', async () => {
  const { readFileSync } = await import('node:fs');
  const base='/tmp/agistack-desktop-test-dist/apps/desktop/src';
  const { normalizeSubagentLifecycleEnvelope } = require(`${base}/hooks/subagentLifecycleEnvelope.js`);
  const { mergeLiveTimelineEvent } = require(`${base}/features/chat/appTimelineEventModel.js`);
  const frames=JSON.parse(readFileSync(new URL('./fixtures/cloud-subagent-cancel-full-timeline.json',import.meta.url),'utf8'));
  const first=frames.find(e=>e.type==='subagent_lifecycle');
  const scope={mode:'cloud',tenantId:first.tenant_id,projectId:first.project_id};
  const items=frames.map(e=>normalizeSubagentLifecycleEnvelope(e,scope)).filter(Boolean).reduce(mergeLiveTimelineEvent,[]);
  const grouping=groupSubAgentTimelineItems(items);
  const actual=grouping.groups.filter(g=>g.runId==='5ecc31031dad45bcb86c5008c42d1d5e');
  assert.equal(actual.length,1);
  assert.equal(actual[0].status,'killed');
  assert.equal(actual[0].items.length,4);
  assert.deepEqual(items.filter(i=>!i.type.startsWith('subagent_')).filter(i=>grouping.claimedItemIds.includes(i.id)),[]);
});

test('terminal coalescing never aliases conversation or execution identities through a shared name', () => {
  const precise=(id,cid,run,type='subagent_killed')=>event(id,type,{conversation_id:cid,run_id:run,execution_id:run,subagent_name:'Same reader'});
  const result=groupSubAgentTimelineItems([
    precise('start','c1','run1','subagent_started'),
    precise('other-child','c1','run2'),
    precise('killed','c1','run1'),
    {id:'parent',type:'observe',payload:{}},
    precise('foreign','c2','run1'),
    precise('ended','c1','run1'),
  ]);
  assert.deepEqual(result.groups.map(g=>g.itemIds),[['start','killed','ended'],['other-child'],['foreign']]);
  assert.ok(!result.claimedItemIds.includes('parent'));
});
