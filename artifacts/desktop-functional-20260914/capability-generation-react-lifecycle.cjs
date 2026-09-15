const fs=require('fs'),assert=require('assert/strict');
const repo=process.cwd(),ts=require(repo+'/agi-stack/apps/desktop/node_modules/typescript');
const React=require('react');
function load(file,imports){const m={exports:{}};new Function('require','module','exports',ts.transpileModule(fs.readFileSync(repo+'/'+file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(name=>imports[name]??require(name),m,m.exports);return m.exports;}
function initializer(file,name){const ast=ts.createSourceFile(file,fs.readFileSync(repo+'/'+file,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);let result;function visit(n){if(ts.isVariableDeclaration(n)&&n.name.getText(ast)===name)result=n.initializer;ts.forEachChild(n,visit);}visit(ast);assert.ok(result);return ts.createPrinter().printNode(ts.EmitHint.Expression,result,ast);}
const appPublication=new Function('useMemo','config','desktopWorkbenchSnapshotOperationsV2','desktopWorkbenchCapabilityClientProviderV2','desktopRendererGenerationV2','return '+initializer('agi-stack/apps/desktop/src/App.tsx','desktopWorkbenchCapabilityClientV2'));
const hostActions=new Function('useMemo','generation','acquireDesktopRendererServiceOperationLeaseV2','acquireDesktopPluginGenerationLeaseV2','AUTHENTICATION_KERNEL_OPERATION_LEASE_V2','return '+ts.transpileModule(initializer('agi-stack/apps/desktop/src/plugins/DesktopRendererGenerationHostV2.tsx','actions'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText.replace(/^\"use strict\";\s*/,''));
const {useDesktopCapabilitySnapshot}=load('agi-stack/apps/desktop/src/features/runtime/useDesktopCapabilitySnapshot.ts',{react:React});
const {createDesktopWorkbenchCapabilityClientProviderV2}=load('agi-stack/apps/desktop/src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts',{});
(async()=>{
 const {Window}=await import(require('url').pathToFileURL(require.resolve('happy-dom',{paths:[repo+'/web']})).href);const win=new Window();global.window=win;global.document=win.document;global.IS_REACT_ACT_ENVIRONMENT=true;
 const {createRoot}=require('react-dom/client');const el=document.createElement('div');const root=createRoot(el);let result,calls=0,signals=[],lateResolve;
 const config={mode:'cloud',tenantId:'t',projectId:'p'};const provider=createDesktopWorkbenchCapabilityClientProviderV2();const actionRef={current:null};
 const operations={async loadSnapshot({signal}){calls++;signals.push(signal);const admission=await actionRef.current.acquireServiceOperationLease({});if(admission.status==='rejected')throw Object.assign(new Error(admission.reasonCode),{reasonCode:admission.reasonCode});return admission.snapshot;}};
 const acquire=async g=>g===undefined?{status:'rejected',reasonCode:'desktop_renderer_service_generation_required'}:g.pending?new Promise(resolve=>lateResolve=resolve):{status:'accepted',snapshot:{id:g.id}};
 function App({generation}){const actions=hostActions(React.useMemo,generation,acquire,()=>({release(){}}),{});React.useLayoutEffect(()=>{actionRef.current=actions;return()=>{actionRef.current=null;}},[actions]);const binding=appPublication(React.useMemo,config,operations,provider,{actions});result=useDesktopCapabilitySnapshot(binding.client,true);return null;}
 const warn=console.warn;console.warn=()=>{};
 try{
 await React.act(async()=>root.render(React.createElement(App,{})));assert.equal(result.snapshot,null);
 const ready={id:'ready'};await React.act(async()=>root.render(React.createElement(App,{generation:ready})));assert.deepEqual(result.snapshot,{id:'ready'});assert.equal(calls,2);
 await React.act(async()=>root.render(React.createElement(App,{generation:ready})));assert.equal(calls,2);
 await React.act(async()=>root.render(React.createElement(App,{generation:{id:'old',pending:true}})));const oldSignal=signals.at(-1);
 await React.act(async()=>root.render(React.createElement(App,{generation:{id:'new'}})));assert.equal(oldSignal.aborted,true);assert.deepEqual(result.snapshot,{id:'new'});
 await React.act(async()=>lateResolve({status:'accepted',snapshot:{id:'old'}}));assert.deepEqual(result.snapshot,{id:'new'});
 await React.act(async()=>root.unmount());console.log('PASS: real React hooks using actual Host actions memo and App client publication: empty generation automatically retries on ready; same generation stable; HMR aborts old load and ignores late result.');
 }finally{console.warn=warn;await win.happyDOM.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
