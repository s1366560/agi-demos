//! First-party MCP transport. Credentials arrive only through the private initialize frame.
mod api;
mod contracts;

use api::{Connector, Provider};
use serde_json::{json, Value};
use std::{
    collections::{btree_map::Entry, BTreeMap},
    sync::Arc,
};
use tokio::{
    io::{AsyncBufRead, AsyncBufReadExt, AsyncWriteExt, BufReader},
    task::{AbortHandle, JoinSet},
};

const MAX_FRAME: usize = 1024 * 1024;

fn response(id: Value, result: Value) -> Value {
    json!({"jsonrpc":"2.0","id":id,"result":result})
}
fn error(id: Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}
fn initialized(
    provider: Provider,
    request: &mut Value,
) -> Result<(Connector, Value), &'static str> {
    let token = match request
        .pointer_mut("/params/_meta/memstack/oauth_access_token")
        .map(Value::take)
    {
        Some(Value::String(token)) => token,
        None | Some(Value::Null) => String::new(),
        _ => return Err("invalid_oauth_credentials"),
    };
    let connector = Connector::new(provider, token)?;
    let version = request
        .pointer("/params/protocolVersion")
        .and_then(Value::as_str)
        .ok_or("invalid_initialize")?;
    if !matches!(version, "2024-11-05" | "2025-03-26" | "2025-06-18") {
        return Err("unsupported_protocol");
    }
    Ok((
        connector,
        json!({"protocolVersion":version,"capabilities":{"tools":{"listChanged":false}},
        "serverInfo":{"name":"memstack-cua-cloud-connectors","version":env!("CARGO_PKG_VERSION"),
        "computer_use_connector":contracts::descriptor(provider.name())}}),
    ))
}
async fn tool_call(connector: Arc<Connector>, id: Value, params: Value) -> Value {
    let Some(name) = params.get("name").and_then(Value::as_str) else {
        return error(id, -32602, "invalid_tool_call");
    };
    let arguments = params
        .get("arguments")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let (output, is_error) = match connector.call(name, &arguments).await {
        Ok(output) => (output, false),
        Err(code) => (json!({"error":{"code":code}}), true),
    };
    response(
        id,
        json!({"content":[{"type":"text","text":output.to_string()}],"structuredContent":output,"isError":is_error}),
    )
}
async fn read_frame<R: AsyncBufRead + Unpin>(reader: &mut R) -> std::io::Result<Option<Vec<u8>>> {
    let mut frame = Vec::new();
    loop {
        let buffer = reader.fill_buf().await?;
        if buffer.is_empty() {
            return if frame.is_empty() {
                Ok(None)
            } else {
                Err(std::io::ErrorKind::UnexpectedEof.into())
            };
        }
        let newline = buffer.iter().position(|byte| *byte == b'\n');
        let count = newline.map_or(buffer.len(), |index| index + 1);
        if frame.len() + count > MAX_FRAME {
            return Err(std::io::ErrorKind::InvalidData.into());
        }
        frame.extend_from_slice(&buffer[..count]);
        reader.consume(count);
        if newline.is_some() {
            return Ok(Some(frame));
        }
    }
}
#[tokio::main]
async fn main() {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let provider = match args.as_slice() {
        [flag, value] if flag == "--provider" => Provider::parse(value),
        _ => Err("provider_required"),
    };
    let Ok(provider) = provider else {
        std::process::exit(2);
    };
    let mut reader = BufReader::new(tokio::io::stdin());
    let mut writer = tokio::io::stdout();
    let mut connector = None;
    let mut tasks = JoinSet::new();
    let mut pending = BTreeMap::<String, AbortHandle>::new();
    loop {
        let output = tokio::select! {
            completed=tasks.join_next(), if !tasks.is_empty()=>{
                match completed {Some(Ok((key,output)))=>{pending.remove(&key);Some(output)},_=>None}
            },
            frame=read_frame(&mut reader)=>{
                let Ok(Some(frame))=frame else {break;};
                let mut request=match serde_json::from_slice::<Value>(&frame){Ok(request)=>request,Err(_)=>break};
                if request["jsonrpc"]!="2.0"{break;}
                let method=request["method"].as_str().unwrap_or("").to_owned();
                if method=="notifications/cancelled" {
                    if let Some(id)=request.pointer("/params/requestId") {if let Some(task)=pending.remove(&id.to_string()){task.abort();}}
                    None
                }else if request.get("id").is_none(){None}
                else {
                    let id=request["id"].clone();let key=id.to_string();
                    match pending.entry(key.clone()) {
                        Entry::Occupied(_)=>Some(error(id,-32600,"duplicate_request_id")),
                        Entry::Vacant(slot)=>if method=="initialize" {
                            if connector.is_some(){Some(error(id,-32600,"already_initialized"))}
                            else {match initialized(provider,&mut request){Ok((client,result))=>{connector=Some(Arc::new(client));Some(response(id,result))},Err(code)=>Some(error(id,-32602,code))}}
                        }else if let Some(client)=connector.as_ref() {
                            match method.as_str(){
                                "ping"=>Some(response(id,json!({}))),
                                "tools/list"=>Some(response(id,json!({"tools":contracts::tools()}))),
                                "tools/call"=>{let client=Arc::clone(client);let params=request["params"].take();let task_key=key.clone();slot.insert(tasks.spawn(async move{(task_key,tool_call(client,id,params).await)}));None},
                                _=>Some(error(id,-32601,"method_not_found")),
                            }
                        }else{Some(error(id,-32002,"initialize_required"))},
                    }
                }
            }
        };
        if let Some(output) = output {
            let Ok(mut bytes) = serde_json::to_vec(&output) else {
                break;
            };
            bytes.push(b'\n');
            if writer.write_all(&bytes).await.is_err() || writer.flush().await.is_err() {
                break;
            }
        }
    }
    tasks.abort_all();
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn initialization_consumes_private_token_and_declares_exact_capabilities() {
        let mut input = json!({"params":{"protocolVersion":"2024-11-05","_meta":{"memstack":{"oauth_access_token":"fixture-only"}}}});
        let (_, output) = initialized(Provider::Google, &mut input).unwrap();
        assert!(input
            .pointer("/params/_meta/memstack/oauth_access_token")
            .unwrap()
            .is_null());
        assert!(!output.to_string().contains("fixture-only"));
        assert_eq!(
            output["serverInfo"]["computer_use_connector"]["provider"],
            "google"
        );
        assert_eq!(contracts::tools().len(), 8);
    }
    #[tokio::test]
    async fn oversized_or_unterminated_frames_fail_without_unbounded_allocation() {
        let data = vec![b'x'; MAX_FRAME + 1];
        let mut reader = BufReader::new(data.as_slice());
        assert!(read_frame(&mut reader).await.is_err());
        let mut reader = BufReader::new(b"{}".as_slice());
        assert!(read_frame(&mut reader).await.is_err());
    }
}
