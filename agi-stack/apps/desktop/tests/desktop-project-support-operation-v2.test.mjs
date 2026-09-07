import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const { createDesktopProjectSupportOperationsV2, DesktopProjectSupportAuthorityUnavailableErrorV2 } = require(`${ROOT}/src/plugins/desktopProjectSupportAuthorityModuleV2.js`);
const config = (overrides={}) => ({apiBaseUrl:'https://api.test',deviceAuthorizationBaseUrl:'',apiKey:'token',localApiToken:'',tenantId:'tenant-1',projectId:'project-1',workspaceId:'',mode:'cloud',workspaceRoot:'',...overrides});
const scope = (authority='cloud') => ({authority,tenantId:'tenant-1',projectId:'project-1'});
const snapshot = (operationScope=scope()) => Object.freeze({scope:operationScope,authority:operationScope.authority,availability:'available',reasonCode:null,serviceVersion:'cloud',contractVersion:'3.0.0',allowedActions:Object.freeze(['view','list','create','close','retry']),authorityRevision:null,tickets:Object.freeze([]),total:0,limit:25,offset:0,hasMore:false});

test('Project Support operations freeze input and acquire one exact project lease', async()=>{
 const lifecycle=[];const received=[];
 const operations=createDesktopProjectSupportOperationsV2(()=>({async acquireServiceOperationLease(request){lifecycle.push(['acquire',request]);return{status:'accepted',digest:'support',useService(operation){return operation(Object.freeze({bindOperation(boundConfig){received.push(boundConfig);return Object.freeze({async list(boundScope,query,options){received.push(boundScope,query,options);return snapshot(boundScope);},async create(){throw new Error('unused');},async close(){throw new Error('unused');}});}}));},async release(){lifecycle.push(['release']);}};}}));
 const runtime=config();const operationScope=scope();const query={limit:25,offset:0};const controller=new AbortController();
 await operations.listSupportTickets({config:runtime,scope:operationScope,query,signal:controller.signal});runtime.tenantId='changed';operationScope.projectId='changed';query.limit=1;
 assert.deepEqual(lifecycle,[['acquire',{service:'service:desktop-renderer.project-support-authority',version:'1.0.0',scope:{kind:'project',tenant_id:'tenant-1',project_id:'project-1'}}],['release']]);
 assert.equal(Object.isFrozen(received[0]),true);assert.equal(Object.isFrozen(received[1]),true);assert.deepEqual(received[2],{limit:25,offset:0});assert.equal(received[3].signal,controller.signal);
});

test('scope mismatch and missing generation fail before service use', async()=>{
 let acquired=0;const operations=createDesktopProjectSupportOperationsV2(()=>({async acquireServiceOperationLease(){acquired+=1;assert.fail();}}));
 assert.throws(()=>operations.listSupportTickets({config:config(),scope:{...scope(),projectId:'other'}}),(error)=>error instanceof RuntimeV2Error&&error.code==='desktop_project_support_operation_input_invalid');assert.equal(acquired,0);
 await assert.rejects(createDesktopProjectSupportOperationsV2(()=>null).listSupportTickets({config:config(),scope:scope()}),(error)=>error instanceof DesktopProjectSupportAuthorityUnavailableErrorV2);
});

test('malformed service fails closed and release never masks primary error',async()=>{
 const primary=new Error('primary');
 await assert.rejects(createDesktopProjectSupportOperationsV2(()=>({async acquireServiceOperationLease(){return{status:'accepted',digest:'x',useService(operation){return operation({bindOperation:()=>({list:async()=>{throw primary;},create:async()=>{},close:async()=>{}})});},async release(){throw new Error('release');}};}})).listSupportTickets({config:config(),scope:scope()}),primary);
 await assert.rejects(createDesktopProjectSupportOperationsV2(()=>({async acquireServiceOperationLease(){return{status:'accepted',digest:'x',useService(operation){return operation({});},async release(){}};}})).listSupportTickets({config:config(),scope:scope()}),(error)=>error instanceof RuntimeV2Error&&error.code==='desktop_project_support_service_invalid');
});
