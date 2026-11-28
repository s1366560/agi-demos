"""Exercise the original message actions through the compiled isolated Web page."""

from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.integration
ASSETS = Path(__file__).resolve().parents[3] / "plugins/business/agent/ui"
RUNTIME = """
const scope = {locale:'en',tenantId:'tenant',projectId:'project',platform:'web',target:'web',
  pathname:'/agent/chat/history',search:'',commands:[],deviceTools:[]};
const messages = [
  {id:'question',role:'user_message',content:'Explain the code',timestamp:1767214800000},
  {id:'reply',role:'assistant_message',content:'```python\\nx = 1\\nprint(x)\\n```',timestamp:1767214810000},
];
window.memstack = {getContext:async()=>scope,invoke:async cmd=>{
  if (cmd==='chat-list') return {items:[{id:'history',title:'Code discussion',execution_target:'cloud'}]};
  if (cmd==='chat-history') return {messages};
  throw Error(cmd);
}};
"""


def test_compiled_message_actions_and_canvas_editor():
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        page.set_content('<div id="root"></div>')
        page.add_script_tag(content=RUNTIME)
        page.add_style_tag(path=ASSETS / "chat-web.css")
        page.add_script_tag(path=ASSETS / "chat-web.js")
        transcript = page.get_by_role("log")
        question = transcript.locator('[data-msg-id="question"]')
        answer = transcript.locator('[data-msg-id="reply"]')
        expect(transcript.locator("time")).to_have_count(2)

        page.get_by_test_id("chat-input").press("Control+f")
        search = page.get_by_role("textbox", name="Search in conversation")
        search.fill("Explain the code")
        expect(question).to_have_css("outline-width", "2px")
        search.press("Escape")
        expect(question).to_have_css("outline-style", "none")

        question.hover()
        question.get_by_role("button", name="Edit", exact=True).click()
        draft = page.get_by_test_id("chat-input")
        expect(draft).to_have_value("Explain the code")
        question.get_by_role("button", name="Reply", exact=True).click()
        expect(draft).to_have_value("> Explain the code\n\n")

        answer.get_by_role("button", name="Open in Canvas", exact=True).click()
        editor = page.get_by_role("textbox", name="Editor for snippet.python")
        expect(editor).to_have_value("x = 1\nprint(x)")
        editor.fill("x = 2")
        page.get_by_role("button", name="Chat mode", exact=True).click()
        page.get_by_role("button", name="Canvas mode", exact=True).click()
        expect(editor).to_have_value("x = 2")


def test_signed_chat_toolbar_tracks_workbench_width_inside_narrow_page():
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_content('<iframe title="Plugin" width="750" height="700"></iframe>')
        frame = page.frames[1]
        frame.set_content('<div id="root"></div>')
        frame.add_script_tag(content=RUNTIME)
        frame.add_style_tag(path=ASSETS / "chat-web.css")
        frame.add_script_tag(path=ASSETS / "chat-web.js")
        send_label = frame.get_by_test_id("send-button").locator("span").get_by_text("Send", exact=True)
        # Older hosts have no appearance width. The legacy fallback also follows the window.
        expect(send_label).to_be_visible()
        frame.evaluate("document.documentElement.dataset.hostBreakpoints = 'sm md'")
        expect(send_label).to_be_hidden()
        frame.evaluate("document.documentElement.dataset.hostBreakpoints = 'sm md lg xl'")
        expect(send_label).to_be_visible()


def test_scoped_lifecycle_control_confirms_and_refreshes_project_actions():
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        page.set_content('<div id="root"></div>')
        page.add_script_tag(content="""
            const calls = [];
            let allowed = ['stop','restart'];
            window.memstack = {
              getContext:async()=>({locale:'en',tenantId:'a',projectId:'fixture',platform:'web',
                target:'web',pathname:'/agent/chat/fixture',search:'',deviceTools:[],
                commands:['chat-project-context','chat-lifecycle-control']}),
              invoke:async(name,payload)=>{
                if(name==='chat-list') return {items:[{id:'fixture',title:'Isolated test',execution_target:'cloud'}]};
                if(name==='chat-history') return {messages:[]};
                if(payload.view==='context-window') throw Error('unavailable');
                if(name==='chat-project-context'){
                  if(payload.view==='lifecycle') return {lifecycle_state:'ready',tool_count:1,
                    skill_count:0,allowed_actions:allowed,pool_managed:false};
                  return {skills:[],entities:[]};
                }
                if(name==='chat-lifecycle-control'){
                  calls.push(payload.action); allowed=[]; return {status:'stopped'};
                }
                throw Error(name);
              },
            };
        """)
        page.add_style_tag(path=ASSETS / "chat-web.css")
        page.add_script_tag(path=ASSETS / "chat-web.js")
        stop = page.get_by_role("button", name="Stop Agent", exact=True)
        expect(stop).to_be_visible()
        expect(page.get_by_role("button", name="Pause", exact=True)).to_have_count(0)
        stop.click()
        expect(page.get_by_role("button", name="Cancel", exact=True)).to_be_visible()
        assert page.evaluate("calls") == []
        page.get_by_role("button", name="Stop", exact=True).click()
        expect(stop).to_have_count(0)
        assert page.evaluate("calls") == ["stop"]


def test_slash_skill_picker_removal_and_scoped_turn_payload():
    with sync_playwright() as pw, pw.chromium.launch() as browser:
        page = browser.new_page()
        # A localhost origin supplies the same secure-context UUID API as the signed frame.
        page.route("http://localhost/agent-test", lambda route: route.fulfill(
            content_type="text/html", body='<div id="root"></div>'
        ))
        page.goto("http://localhost/agent-test")
        page.add_script_tag(content=RUNTIME)
        page.add_script_tag(content="""
            scope.commands = ['chat-project-context','chat-turn'];
            const base = window.memstack.invoke;
            const turns = [];
            window.memstack.invoke = async (name, payload, options) => {
              if (name === 'chat-project-context') {
                if (payload.view === 'commands') return {commands:[],skills:[
                  {id:'fixture-skill',name:'summarize',description:'Summarize project notes'},
                ]};
                if (payload.view === 'lifecycle') return {lifecycle_state:'ready',tool_count:1,skill_count:1};
                throw Error('unavailable');
              }
              if (name === 'chat-turn') {
                turns.push(payload);
                options.onEvent({type:'accepted',run_id:'turn-'+turns.length,revision:1});
                await new Promise(resolve => { window.finishTurn = resolve; });
                return {};
              }
              return base(name, payload, options);
            };
        """)
        page.add_style_tag(path=ASSETS / "chat-web.css")
        page.add_script_tag(path=ASSETS / "chat-web.js")
        draft = page.get_by_test_id("chat-input")
        picker = page.get_by_role("listbox")
        skill = picker.get_by_role("option").filter(has_text="summarize")
        chip = page.get_by_role("button", name="Remove /summarize skill")
        draft.fill("/sum")
        skill.click()
        expect(chip).to_be_visible()
        expect(draft).to_have_value("")
        chip.click()
        expect(chip).to_have_count(0)

        draft.fill("Without skill")
        page.get_by_test_id("send-button").click()
        page.wait_for_function("turns.length === 1")
        assert "forced_skill_name" not in page.evaluate("turns[0]")
        page.evaluate("window.finishTurn()")
        expect(draft).to_be_enabled()

        draft.fill("/sum")
        expect(skill).to_be_visible()
        draft.press("Enter")
        expect(picker).to_have_count(0)
        expect(chip).to_be_visible()
        draft.fill("Summarize my notes")
        draft.press("Enter")
        page.wait_for_function("turns.length === 2")
        turn = page.evaluate("turns[1]")
        assert turn["forced_skill_name"] == "summarize"
        assert turn["message"] == "Summarize my notes"
        assert turn["conversation_id"] == "history"
        expect(chip).to_have_count(0)
        page.evaluate("window.finishTurn()")
