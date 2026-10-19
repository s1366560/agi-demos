//! Exact, declared OAuth API operations; no text-based intent classification.
use serde_json::{json, Value};

pub fn tools() -> Vec<Value> {
    let string = json!({"type":"string","minLength":1});
    let contact = json!({"type":"object","minProperties":1,"additionalProperties":false,"properties":{
        "given_name":{"type":"string"},"family_name":{"type":"string"},
        "email_address":{"type":"string"},"phone_number":{"type":"string"}}});
    [
        ("calendar_list",true,false,json!({"calendar_id":string,"start":string,"end":string,"page_token":string,"limit":{"type":"integer","minimum":1,"maximum":250}}),vec![]),
        ("calendar_create",false,false,json!({"calendar_id":string,"event":{"type":"object"}}),vec!["event"]),
        ("calendar_update",false,false,json!({"calendar_id":string,"event_id":string,"event":{"type":"object"}}),vec!["event_id","event"]),
        ("calendar_delete",false,true,json!({"calendar_id":string,"event_id":string}),vec!["event_id"]),
        ("contacts_list",true,false,json!({"page_token":string,"limit":{"type":"integer","minimum":1,"maximum":250}}),vec![]),
        ("contacts_create",false,false,json!({"contact":contact}),vec!["contact"]),
        ("contacts_update",false,false,json!({"contact_id":string,"etag":string,"contact":contact}),vec!["contact_id","etag","contact"]),
        ("contacts_delete",false,true,json!({"contact_id":string}),vec!["contact_id"]),
    ].into_iter().map(|(name,read,destructive,properties,required)|json!({
        "name":name,"description":format!("{} on the explicitly connected account. Event bodies follow this provider's published API schema; creating/updating attendees can send invitations. Writes require per-action approval.",name),
        "inputSchema":{"type":"object","properties":properties,"required":required,"additionalProperties":false},
        "annotations":{"readOnlyHint":read,"destructiveHint":destructive,"idempotentHint":read,"openWorldHint":true}
    })).collect()
}
pub fn descriptor(provider: &str) -> Value {
    json!({"provider":provider,"capabilities":{
        "calendar":["calendar_list","calendar_create","calendar_update","calendar_delete"],
        "contacts":["contacts_list","contacts_create","contacts_update","contacts_delete"]}})
}
pub fn validate(name: &str, args: &Value) -> Result<(), &'static str> {
    let definition = tools()
        .into_iter()
        .find(|tool| tool["name"] == name)
        .ok_or("unknown_tool")?;
    let validator =
        jsonschema::draft202012::new(&definition["inputSchema"]).map_err(|_| "invalid_schema")?;
    if validator.is_valid(args) {
        Ok(())
    } else {
        Err("invalid_arguments")
    }
}
