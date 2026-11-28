from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

UI = Path(__file__).resolve().parents[1] / "ui"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("path", "bundle", "title"),
    [
        ("/tenant/t/deploy", "tenant-deploy", "Deploy Records"),
        ("/tenant/t/deploy/d1", "tenant-deploy", "d1"),
        ("/tenant/t/instance-templates", "tenant-deploy", "Instance Templates"),
        ("/tenant/t/instance-templates/r1", "tenant-deploy", "Assistant image"),
        ("/tenant/t/instances/create", "tenant-deploy", "Create Instance"),
        ("/tenant/t/deploy/d1", "deployments-desktop", "d1"),
        ("/tenant/t/instance-templates/r1", "templates-desktop", "Assistant image"),
    ],
)
def test_original_environment_bookmarks(path, bundle, title):
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page()
        page.route(
            "https://renderer.test/",
            lambda r: r.fulfill(content_type="text/html", body='<div id="root"></div>'),
        )
        page.goto("https://renderer.test/")
        page.evaluate(
            """path => {
          const deployment={id:'d1',instance_id:'i1',action:'create',revision:1,status:'success',created_at:'2026-11-01T00:00:00Z',config_snapshot:{}};
          const template={id:'r1',tenant_id:'t',name:'Assistant image',slug:'assistant',is_published:false,
            created_at:'2026-11-01T00:00:00Z',default_config:{},description:'Ready',install_count:0};
          window.memstack={getContext:async()=>({locale:'en',tenantId:'t',projectId:null,pathname:path,search:path.endsWith('/create')?'?templateId=r1':'',hash:''}),
          navigate:async(value)=>{window.destination=value}, invoke:async (command,body)=>{
            if(command==='environment-inventory')return {items:[],total:0};
            if(command==='read-deploys')return body.view==='list'?{deployments:[deployment],page:1,page_size:20,total:1}:deployment;
            if(command==='read-instance-templates')return body.view==='list'?{templates:[template],total:1,page:1,page_size:20}:body.view==='detail'?template:{items:[]};
            throw Error('unexpected command');
          }};
        }""",
            path,
        )
        page.add_style_tag(path=UI / (bundle + ".css"))
        page.add_script_tag(path=UI / (bundle + ".js"))
        expect(page.get_by_text(title, exact=False).first).to_be_visible()
        if path.endswith("/r1") and bundle == "tenant-deploy":
            page.get_by_role("button", name="Deploy from Template").click()
            assert page.evaluate("window.destination") == "/tenant/t/instances/create?templateId=r1"
