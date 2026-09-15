const fs=require('fs'),path=require('path'),Module=require('module'),assert=require('assert/strict');
const repo='/Users/tiejunsun/github/agi-demos';
const ts=require(repo+'/agi-stack/apps/desktop/node_modules/typescript');
const original=Module._load,cache={};
function sourceModule(file){if(file.endsWith('.css'))return {};if(!fs.existsSync(file)&&file.endsWith('.ts'))file+='x';if(cache[file])return cache[file].exports;const m={exports:{}};cache[file]=m;new Function('require','module','exports',ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText)(s=>s.startsWith('.')?sourceModule(path.resolve(path.dirname(file),s)+(s.endsWith('.css')?'':'.ts')):require(s),m,m.exports);return m.exports;}
(async()=>{
 const {Window}=await import(require('url').pathToFileURL(require.resolve('happy-dom',{paths:[repo+'/web']})).href);
 const win=new Window({url:'http://localhost/'});global.window=win;global.document=win.document;global.HTMLElement=win.HTMLElement;global.IS_REACT_ACT_ENVIRONMENT=true;
 const React=require('react');const {act}=React;const {createRoot}=require('react-dom/client');
 const {LocalPluginSettings}=sourceModule(repo+'/agi-stack/apps/desktop/src/features/settings/LocalPluginSettings.tsx');
 const {I18nContext}=sourceModule(repo+'/agi-stack/apps/desktop/src/i18nContext.ts');
 const config={mode:'local',tenantId:'tenant-1',projectId:'project-1',apiBaseUrl:'http://127.0.0.1:49999',apiKey:'fixture',localApiToken:'fixture-launch'};
 const scope={kind:'project',tenant_id:'tenant-1',project_id:'project-1'};
 const reference={bundle_id:'fixture-plugin',version:'1.0.0',digest:'sha256:'+'a'.repeat(64),source:'local-file://fixture-plugin/1.0.0'};
 let rows=[];let trustConfigured=true;const requests=[];let pendingInspect=null;let deferInspect=false;
 global.fetch=async (url,options)=>{ const u=new URL(url);const body=options.body?JSON.parse(options.body):null;requests.push({path:u.pathname,body});let response;
  if(u.pathname.endsWith('/inspect') && deferInspect) await new Promise(resolve=>{pendingInspect=resolve;});
  if(u.pathname.endsWith('/enable')) return new Response(JSON.stringify({detail:'host denied fixture'}),{status:503,headers:{'Content-Type':'application/json'}});
  if(u.pathname.endsWith('/inspect'))response={reference,scope,verified:true,declared_permissions:['file:read','network:connect'],plugins:[{plugin_id:'fixture-tool',version:'1.0.0'}]};
  else if(u.pathname.endsWith('/import')){rows=[{reference,scope,enabled:true,authorization_status:'approved',activation_status:'pending',activation_error:null,approved_permissions:body.approved_permissions}];response={reference,scope,status:'installed'};}
  else if(u.pathname.endsWith('/disable')){rows[0]={...rows[0],enabled:false,activation_status:'inactive',activation_error:null};response={reference,scope,status:'disabled'};}
  else if(u.pathname.endsWith('/revoke')){rows[0]={...rows[0],enabled:false,activation_status:'inactive',activation_error:null,authorization_status:'revoked',approved_permissions:[]};response={reference,scope,status:'revoked'};}
  else if(u.pathname.endsWith('/uninstall')){rows=[];response={reference,scope,status:'uninstalled'};}
  else response={installations:rows,trust_configured:trustConfigured};
  return new Response(JSON.stringify(response),{status:200,headers:{'Content-Type':'application/json'}});
 };
 win.__MEMSTACK_DESKTOP__={files:{open:async()=>({status:'selected',files:[{filename:'fixture.mspkg',mimeType:'application/octet-stream',bytes:Uint8Array.from([80,75,3,4])}]})}};
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const render=(activeConfig=config)=>React.createElement(I18nContext.Provider,{value:{locale:'en',setLocale(){},t:k=>k}},React.createElement(LocalPluginSettings,{config:activeConfig,canManage:true}));
 const button=(key)=>[...host.querySelectorAll('button')].find(b=>b.textContent===key);
 await act(async()=>root.render(render()));
 if(button('localPlugins.choose').disabled) console.log(host.textContent, requests);
 assert.equal(button('localPlugins.choose').disabled,false);
 await act(async()=>button('localPlugins.choose').click());
 assert.equal(button('localPlugins.install').disabled,true);assert.equal(requests.filter(r=>r.path.endsWith('/import')).length,0);
 const checks=[...host.querySelectorAll('input[type=checkbox]')];assert.equal(checks.length,3);
 for(const check of checks)await act(async()=>check.click());
 assert.equal(button('localPlugins.install').disabled,false);
 await act(async()=>button('localPlugins.install').click());
 assert.deepEqual(requests.find(r=>r.path.endsWith('/import')).body.approved_permissions,['file:read','network:connect']);
 assert.match(host.textContent,/localPlugins.activation.pending/);assert.doesNotMatch(host.textContent,/localPlugins.activation.active/);
 rows[0]={...rows[0],activation_status:'active'};
 await act(async()=>button('localPlugins.refresh').click());assert.match(host.textContent,/localPlugins.activation.active/);
 await act(async()=>button('localPlugins.disable').click());assert.match(host.textContent,/localPlugins.disabled/);
 await act(async()=>button('localPlugins.enable').click());assert.match(host.textContent,/host denied fixture/);assert.match(host.textContent,/localPlugins.disabled/);
 await act(async()=>button('localPlugins.revoke').click());assert.equal(requests.filter(r=>r.path.endsWith('/revoke')).length,0);
 await act(async()=>button('localPlugins.confirm').click());assert.match(host.textContent,/localPlugins.revoked/);assert.equal(button('localPlugins.enable').disabled,true);
 await act(async()=>button('localPlugins.uninstall').click());await act(async()=>button('localPlugins.confirm').click());assert.match(host.textContent,/localPlugins.empty/);
 rows=[{reference,scope,enabled:true,authorization_status:'approved',approved_permissions:[],activation_status:'failed',activation_error:'Archive signature invalid <script>bad()</script>'}];trustConfigured=false;
 await act(async()=>button('localPlugins.refresh').click());
 assert.match(host.textContent,/localPlugins.activation.failed: Archive signature invalid/);
 assert.equal(host.querySelectorAll('script').length,0);
 assert.equal(button('localPlugins.choose').disabled,true);assert.equal(button('localPlugins.uninstall').disabled,false);
 await act(async()=>button('localPlugins.uninstall').click());await act(async()=>button('localPlugins.confirm').click());assert.match(host.textContent,/localPlugins.empty/);
 trustConfigured=true;await act(async()=>button('localPlugins.refresh').click());
 deferInspect=true;
 await act(async()=>button('localPlugins.choose').click());
 assert.equal(typeof pendingInspect,'function');
 await act(async()=>root.render(render({...config,projectId:'project-2'})));
 await act(async()=>pendingInspect());
 assert.match(host.textContent,/project-2/);assert.doesNotMatch(host.textContent,/localPlugins.inspect|fixture-plugin/);
 await act(async()=>root.unmount());await win.happyDOM.close();
 console.log('PASS: React permission/scope approval, mock HTTP boundary requests, disable, server error retention, explicit revoke confirmation, revoked-enable denial, uninstall refresh, pending/active transitions, failed activation with missing trust remains uninstallable and escaped, stale inspection discarded on project switch.');
})().catch(e=>{console.error(e);process.exitCode=1;});
