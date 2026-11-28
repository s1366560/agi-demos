"""Reopen the original native edit dialog and submit its revision-bound mutation."""

from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.integration
def test_native_schedule_editor_restores_bound_revision():
    ui = Path(__file__).resolve().parents[1] / "ui"
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.route(
            "https://schedule.test/",
            lambda route: route.fulfill(content_type="text/html", body='<div id="root"></div>'),
        )
        page.goto("https://schedule.test/")
        page.evaluate("""() => {
            const job = {id:'selected', project_id:'p', name:'My schedule', revision:7, enabled:false,
              schedule:{kind:'every',config:{interval_seconds:90}},
              payload:{kind:'system_event', config:{content:'A task'}},
              delivery:{kind:'none',config:{}}, state:{}, conversation_mode:'fresh', timezone:'UTC'};
            window.memstack = {
              getContext: async () => ({projectId:'p',tenantId:'t',locale:'en',target:'desktop-renderer',pathname:'/cron-jobs',
                search:'?panel=edit&job=selected',hash:'#past',commands:['run-schedule','schedule-conversations']}),
              navigate: async (path) => {window.lastPath=path;},
              invoke: async (command, input) => {
                if (command === 'save-schedule') {window.saved=input; job.name=input.name; return job;}
                if (command === 'schedule-conversations') return {items:[]};
                if (input.view === 'job') return job;
                if (input.view === 'capabilities') return {read:true,revision_guarded:true,idempotency_guarded:true,
                  durable_execution:true,edit:{allowed:true},toggle:{allowed:true},create:{allowed:true},delete:{allowed:true},run_now:{allowed:true}};
                return {items: input.job_id ? [] : [job],total: input.job_id ? 0 : 1};
              }
            };
        }""")
        page.add_style_tag(path=ui / "cron-jobs.css")
        page.add_script_tag(path=ui / "cron-jobs.js")
        form = page.get_by_role("dialog")
        expect(form.locator("input[id=name]")).to_have_value("My schedule")
        form.locator("input[id=name]").fill("Updated schedule")
        form.get_by_role("button", name="Save Changes").click()
        expect(form).not_to_be_visible()
        saved = page.evaluate("window.saved")
        assert saved["expected_revision"] == 7
        assert saved["trigger"] == {"kind": "every", "interval_seconds": 90}
        assert saved["name"] == "Updated schedule" and saved["idempotency_key"]
        assert page.evaluate("window.lastPath") == "/cron-jobs#past"
