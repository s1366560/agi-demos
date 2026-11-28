"""Exercise the Agent's compiled Web and desktop guests with a deterministic capability fixture."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3] / "plugins/business/agent/ui"
RUNTIME = """
const scope={locale:'en',tenantId:'tenant',projectId:'project',platform:PLATFORM,
  target:PLATFORM, pathname:'/agent/chat/origin',search:'',hash:'',deviceTools:[],
  commands:['activity-list','activity-mark','review-latest','review-details']};
let entries=[];
const item={id:'agent_run:run', authority_kind:'agent_run',authority_id:'run',run_id:'run',
  conversation_id:'conversation', project_id:'project', workspace_id:null,
  title:'Review fixture task', group:'ready_review',status:'completed',required_action:'observe',
  revision:3,created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:01:00Z'};
window.calls=[];
window.memstack={getContext:async()=>scope,navigate:async(path,options)=>{window.calls.push(['navigate',{path,...options}]);},invoke:async(cmd,p)=>{
  window.calls.push([cmd,p]);
  if(cmd==='chat-list')return {items:[{id:'origin',title:'Origin',execution_target:'cloud'},{id:'conversation',title:'Fixture',execution_target:'cloud'}]};
  if(cmd==='chat-history')return {messages:[]};
  if(cmd==='activity-list')return p.view==='items'?{principal_id:'reader',items:[item]}:
    {principal_id:'reader',project_id:'project',authority_revision:3,entries};
  if(cmd==='activity-mark'){entries=p.entries;return {project_id:'project',authority_revision:4,entries};}
  if(cmd==='review-latest')return {latest_run:p.conversation_id==='origin'?null:{id:'run',turn_id:'turn',conversation_id:'conversation',
    revision:3,status:'completed',execution_target:'cloud',permission_profile:'read_only'}};
  if(cmd==='review-details')return p.view==='summary'?{status:'completed',completion_summary:'Recorded summary'}:
    {status:'ready',additions:2,deletions:1,files:[]};
  throw new Error(cmd);
}};
"""


@pytest.mark.parametrize("platform", ["web", "desktop-renderer"])
def test_compiled_agent_review_and_receipts(platform):
    desktop = platform == "desktop-renderer"
    target = "desktop" if desktop else "web"
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(locale="en-US")
        page.set_content('<div id="root"></div>')
        page.add_script_tag(content=RUNTIME.replace("PLATFORM", repr(platform)))
        page.add_style_tag(path=ROOT / f"chat-{target}.css")
        page.add_script_tag(path=ROOT / f"chat-{target}.js")
        inbox = re.compile("Activity inbox|Open Activity and My Work", re.I)
        page.get_by_role("button", name=inbox).click()
        expect(page.get_by_text("Review fixture task", exact=True)).to_be_visible()
        mark = page.get_by_role("button", name=re.compile("mark all (?:as )?read", re.I))
        mark.click()
        expect(mark).to_be_disabled()
        assert (
            page.evaluate(
                "calls.find(([name])=>name==='activity-mark')[1].expected_authority_revision"
            )
            == 3
        )
        page.get_by_role("button", name=re.compile("Review fixture task")).click()
        if desktop:
            assert page.evaluate("calls.find(([name])=>name==='navigate')[1]") == {
                "path": "/agent/chat/origin?conversationId=conversation",
                "replace": True,
            }
            page.get_by_role("button", name="Run context").click()
            expect(page.locator(".session-context-facts")).to_contain_text("read_only")
        page.get_by_role("button", name="Run review").click()
        expect(page.get_by_text("Recorded summary")).to_be_visible()
        page.get_by_role("button", name="turn", exact=True).click()
        page.wait_for_function(
            "calls.some(([name,p])=>name==='review-details' && p.scope==='turn' && p.expected_revision===3 && p.turn_id==='turn')"
        )
