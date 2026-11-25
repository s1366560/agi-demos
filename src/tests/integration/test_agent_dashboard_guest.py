"""Exercise both compiled tenant dashboard guests against scoped trace command fixtures."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3] / "plugins/business/agent/ui"

RUNTIME = """
const tenant = 'fixture-tenant';
const time = '2026-01-01T00:00:00Z';
const run = {run_id:'run',conversation_id:'conversation',subagent_name:'Fixture explorer',
 task:'',status:'completed',created_at:time,started_at:time,ended_at:time,summary:null,
 error:null,execution_time_ms:10,tokens_used:1,trace_id:'trace',parent_span_id:null};
const views = {config:{id:'config',tenant_id:tenant,config_type:'default',llm_model:'fixture-model',
 llm_temperature:0.2,pattern_learning_enabled:false,multi_level_thinking_enabled:false,
 max_work_plan_steps:10,tool_timeout_seconds:30,enabled_tools:[],disabled_tools:[],runtime_hooks:[],
 runtime_hook_settings_redacted:true,multi_agent_enabled:true,authority_revision:1,
 created_at:time,updated_at:time},permission:{can_modify:false},runs:{tenant_id:tenant,runs:[run],total:1},
 active:{tenant_id:tenant,active_count:0},system:{edition:'community',features:[],agent_runtime:{mode:'auto'},
 memory_runtime:{mode:'managed',tool_provider_mode:'internal',failure_persistence_enabled:false}}};
window.calls=[];
window.memstack={getContext:async()=>({locale:'en',target:PLATFORM,tenantId:tenant,projectId:null,
 pathname:'/tenant/fixture-tenant/agents',commands:['dashboard-read','dashboard-trace','dashboard-configure']}),
 invoke:async(cmd,payload)=>{window.calls.push([cmd,payload]);
 if(cmd==='dashboard-read')return views[payload.view];
 if(cmd==='dashboard-trace')return {conversation_id:'conversation',trace_id:'trace',total:2,runs:[
 {...run,task:'Authorized parent task'},{...run,run_id:'child',subagent_name:'Nested fixture agent',
 parent_span_id:'run',task:'Authorized child task'}]};
 throw Error(cmd);}};
"""


@pytest.mark.parametrize("target", ["web", "desktop"])
def test_original_dashboard_opens_scoped_trace_chain(target: str) -> None:
    with sync_playwright() as api:
        browser = api.chromium.launch()
        page = browser.new_page()
        page.set_content('<div id="root"></div>')
        page.add_script_tag(content=RUNTIME.replace("PLATFORM", repr(target)))
        page.add_style_tag(path=ROOT / f"{target}-dashboard.css")
        page.add_script_tag(path=ROOT / f"{target}-dashboard.js")
        agent = page.get_by_text("Fixture explorer", exact=True)
        if target == "web":
            page.get_by_role("button", name=re.compile("trace", re.I)).first.click()
        agent.first.click()
        expect(page.get_by_text("Nested fixture agent", exact=True)).to_be_visible()
        assert page.evaluate("calls.filter(([c])=>c==='dashboard-trace')") == [
            ["dashboard-trace", {"conversation_id": "conversation", "trace_id": "trace"}]
        ]
        assert not page.get_by_role("button", name=re.compile("edit configuration", re.I)).count()
        browser.close()
