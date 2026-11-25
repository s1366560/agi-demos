"""Exercise the original signed event filters and webhook editor in Chromium."""

from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

UI = Path(__file__).resolve().parents[1] / "ui"


@pytest.mark.integration
@pytest.mark.parametrize("segment", ["events", "webhooks"])
@pytest.mark.parametrize("target", ["web", "desktop-renderer"])
def test_signed_tenant_activity_controls(segment, target):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content('<div id="root"></div>')
        page.evaluate(
            """([segment, target]) => {
              const pathname = '/tenant/acme/' + segment;
              window.calls = [];
              window.memstack = {
                getContext: async () => ({
                  tenantId: 'acme', target, locale: 'en-US', pathname,
                  search: segment === 'events' ? '?type=job.started' : '', hash: '',
                }),
                navigate: async () => {},
                invoke: async (command, data) => {
                  window.calls.push({command,data});
                  if (command === 'event-types') return {items:['job.started']};
                  if (command === 'list-webhooks') return {items:[]};
                  if (command === 'read-events') return {total:1, items:[{
                    id:'e', event_type:'job.started', message:'A job started', source:'worker',
                    created_at:'2026-01-01T00:00:00Z',
                  }]};
                  throw new Error('unexpected command');
                },
              };
            }""",
            [segment, target],
        )
        page.add_style_tag(path=UI / "tenant-activity.css")
        page.add_script_tag(path=UI / "tenant-activity.js")
        if segment == "webhooks":
            page.get_by_role("button", name="Create Webhook").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.get_by_role("textbox", name="URL")).to_be_visible()
        else:
            expect(page.get_by_text("A job started")).to_be_visible()
            query = page.evaluate("window.calls.find(c => c.command === 'read-events').data")
            assert query == {"page": 1, "page_size": 20, "event_type": "job.started"}
        browser.close()


@pytest.mark.integration
def test_saved_workflow_revision_after_pagination():
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.set_content('<div id="root"></div>')
        page.evaluate("""() => {
          window.memstack = {
            scope: async () => ({locale:'en',commands:['save-workflow'],pathname:'/automation',
              search:'?workflow=second&revision=2',hash:''}),
            navigate: async () => {},
            invoke: async (command, args) => {
              if (command === 'list-workflows') {
                return args.after
                  ? {items:[{id:'second',revision:2,name:'Weekly check',intervals:[124]}],next_cursor:null}
                  : {items:[{id:'first',revision:1,name:'First',intervals:[20]}],next_cursor:'next'};
              }
              if (command === 'execute-workflow') {
                if (args.id !== 'second' || args.revision !== 2) throw Error('wrong revision');
                return {results:[{next_run_at:'2027-01-02T00:00:00Z'}]};
              }
            },
          };
        }""")
        page.add_script_tag(path=UI / "workflow.js")
        expect(page.get_by_label("Workflow name")).to_have_value("Weekly check")
        expect(page.get_by_label("Interval in seconds")).to_have_value("124")
        page.get_by_role("button", name="Run saved revision").click()
        expect(page.get_by_text("2027-01-02T00:00:00Z")).to_be_visible()


@pytest.mark.integration
def test_signed_run_history_bookmark_restores_job_and_page():
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.set_content('<div id="root"></div>')
        page.evaluate("""() => {
          window.calls = [];
          window.memstack = {
            getContext: async () => ({locale:'en',projectId:'p',commands:[],pathname:'/cron-jobs',
              search:'?panel=runs&job=abc&runsPage=2',hash:''}),
            navigate: async () => {},
            invoke: async (_, args) => {
              window.calls.push(args);
              if (args.view === 'capabilities') return Object.fromEntries(
                ['create','edit','toggle','run_now','delete'].map(action=>[action,{allowed:true}]));
              return {items:[],total:0};
            },
          };
        }""")
        page.add_style_tag(path=UI / "cron-jobs.css")
        page.add_script_tag(path=UI / "cron-jobs.js")
        expect(page.get_by_role("dialog")).to_be_visible()
        query = page.evaluate("window.calls.find(c => c.job_id === 'abc')")
        assert query["offset"] == 10
        assert query["limit"] == 10
