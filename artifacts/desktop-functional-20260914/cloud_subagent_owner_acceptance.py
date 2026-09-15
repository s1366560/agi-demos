"""Formal QA HTTP/WS exercise; credentials remain in process and are revoked."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import websockets

PROJECT = '738ace12-0d21-48ca-847d-cd0c2802816d'
TENANT = '02f6fccc-0ac9-4729-bac7-38e77d1c61ef'
WORKSPACE = 'b30bf32d-36f0-4832-bcca-252a8df18b15'
OUT = Path('artifacts/desktop-functional-20260914/cloud-subagent-owner-formal.json')

async def main():
    report = {'events': [], 'snapshots': []}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=30) as client:
        login = await client.post('/api/v1/auth/token', data={'username':'admin@memstack.ai','password':'adminpassword'})
        login.raise_for_status()
        token = login.json()['access_token']
        client.headers.update({'Authorization': 'Bearer '+token, 'X-Tenant-ID': TENANT})
        try:
            response = await client.post('/api/v1/agent/conversations', json={'project_id':PROJECT, 'workspace_id':WORKSPACE,'title':'QA owner cancellation 20260914','agent_config':{'selected_agent_id':'builtin:all-access','capability_mode':'work'}})
            report['create_status'] = response.status_code
            response.raise_for_status()
            cid = response.json()['id']
            report['conversation_id'] = cid
            print(json.dumps({'conversation_id':cid}), flush=True)
            async with websockets.connect('ws://127.0.0.1:8000/api/v1/agent/ws?token='+token, max_size=4*1024*1024) as ws:
                await ws.send(json.dumps({'type':'send_message','conversation_id':cid,'project_id':PROJECT,'client_message_id':str(uuid4()),'permission_mode':'full_access','message':'这是已授权的 QA 后台子智能体取消验收。直接执行，不创建计划，不读写任何文件。首先仅调用 sessions_spawn 创建 architect，任务为：不调用任何工具，用中文详细论述分布式一致性的数学基础，至少一万字。父任务获得 run_id 后立刻用 subagents action=kill 取消这个 run_id，然后调用 sessions_wait 与 sessions_history 查看它的最终状态与历史。请务必实际使用这些工具，最后只报告实际观察的状态及 run_id；不要等待子任务完成后才取消。'}) )
                deadline = asyncio.get_running_loop().time()+150
                while asyncio.get_running_loop().time()<deadline:
                    try:
                        msg=json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    except TimeoutError:
                        msg={}
                    typ=msg.get('type','')
                    data=msg.get('data') or {}
                    safe={'type':typ}
                    for source in (msg, data if isinstance(data,dict) else {}):
                        for key in ('event_type','conversation_id','run_id','tool_name','status','code'):
                            if key in source:safe[key]=source[key]
                    if typ and typ not in ('ping','pong','text_delta','thought_delta','thinking_delta'):
                        report['events'].append(safe)
                        print(json.dumps(safe),flush=True)
                    if len(report['events'])%5==0 or not typ:
                        trace=await client.get(f'/api/v1/agent/trace/runs/{cid}')
                        if trace.status_code==200:
                            runs=trace.json().get('runs',[])
                            snapshot=[{'run_id':r.get('run_id'),'status':r.get('status'),'metadata':r.get('metadata')} for r in runs]
                            if snapshot and (not report['snapshots'] or report['snapshots'][-1]!=snapshot):
                                report['snapshots'].append(snapshot)
                                print(json.dumps({'child_states':[(r['run_id'],r['status']) for r in snapshot]}),flush=True)
                    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
                    if typ in ('complete','execution_completed'):
                        break
                else:
                    await ws.send(json.dumps({'type':'stop_session','conversation_id':cid}))
                    report['deadline_stop_requested']=True
            trace=await client.get(f'/api/v1/agent/trace/runs/{cid}')
            report['final_trace_status']=trace.status_code
            if trace.status_code==200:report['final_trace']=trace.json()
        finally:
            revoked=await client.post('/api/v1/auth/signout')
            report['credential_revocation_status']=revoked.status_code
            OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2))

asyncio.run(main())
