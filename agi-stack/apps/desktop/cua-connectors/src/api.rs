//! OAuth bearer handling stays in memory; HTTP errors never expose provider bodies.
use futures_util::StreamExt;
use reqwest::{Client, Method};
use serde_json::{json, Value};
use url::Url;
use zeroize::Zeroizing;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Provider {
    Google,
    Microsoft365,
}
impl Provider {
    pub fn parse(value: &str) -> Result<Self, &'static str> {
        match value {
            "google" => Ok(Self::Google),
            "microsoft365" => Ok(Self::Microsoft365),
            _ => Err("unsupported_provider"),
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Google => "google",
            Self::Microsoft365 => "microsoft365",
        }
    }
}
pub struct Connector {
    provider: Provider,
    token: Zeroizing<String>,
    client: Client,
    calendar: Url,
    contacts: Url,
}
impl Connector {
    pub fn new(provider: Provider, token: String) -> Result<Self, &'static str> {
        let client = Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| "client_unavailable")?;
        let (calendar, contacts) = match provider {
            Provider::Google => (
                "https://www.googleapis.com/calendar/v3/",
                "https://people.googleapis.com/v1/",
            ),
            Provider::Microsoft365 => (
                "https://graph.microsoft.com/v1.0/",
                "https://graph.microsoft.com/v1.0/",
            ),
        };
        Ok(Self {
            provider,
            token: Zeroizing::new(token),
            client,
            calendar: Url::parse(calendar).map_err(|_| "invalid_origin")?,
            contacts: Url::parse(contacts).map_err(|_| "invalid_origin")?,
        })
    }
    pub async fn call(&self, name: &str, args: &Value) -> Result<Value, &'static str> {
        crate::contracts::validate(name, args)?;
        if self.token.is_empty() {
            return Err("oauth_required");
        }
        let (method, url, body) = self.request(name, args)?;
        let mut request = self
            .client
            .request(method.clone(), url)
            .bearer_auth(self.token.as_str());
        if self.provider == Provider::Microsoft365 && name == "contacts_update" {
            let etag = reqwest::header::HeaderValue::from_str(
                args["etag"].as_str().ok_or("invalid_arguments")?,
            )
            .map_err(|_| "invalid_arguments")?;
            request = request.header(reqwest::header::IF_MATCH, etag);
        }
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request.send().await.map_err(|_| {
            if method == Method::GET {
                "provider_unreachable"
            } else {
                "action_outcome_unknown"
            }
        })?;
        if response.status().as_u16() == 401 {
            return Err("oauth_expired");
        }
        if response.status().as_u16() == 403 {
            return Err("account_permission_denied");
        }
        if !response.status().is_success() {
            return Err("provider_request_failed");
        }
        if response.status().as_u16() == 204 {
            return Ok(json!({"ok":true}));
        }
        let mut stream = response.bytes_stream();
        let mut bytes = Vec::new();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|_| {
                if method == Method::GET {
                    "provider_response_lost"
                } else {
                    "action_outcome_unknown"
                }
            })?;
            if bytes.len() + chunk.len() > 1024 * 1024 {
                return Err("provider_response_too_large");
            }
            bytes.extend_from_slice(&chunk);
        }
        serde_json::from_slice(&bytes).map_err(|_| {
            if method == Method::GET {
                "invalid_provider_response"
            } else {
                "action_outcome_unknown"
            }
        })
    }
    fn request(
        &self,
        name: &str,
        args: &Value,
    ) -> Result<(Method, Url, Option<Value>), &'static str> {
        let calendar = args
            .get("calendar_id")
            .and_then(Value::as_str)
            .unwrap_or("primary");
        let event_id = args.get("event_id").and_then(Value::as_str).unwrap_or("");
        let contact_id = args.get("contact_id").and_then(Value::as_str).unwrap_or("");
        let limit = args
            .get("limit")
            .and_then(Value::as_u64)
            .unwrap_or(100)
            .to_string();
        let read = name.ends_with("_list");
        let mut url = if name.starts_with("calendar_") {
            let mut segments = match self.provider {
                Provider::Google => vec!["calendars", calendar, "events"],
                Provider::Microsoft365 => {
                    if args.get("calendar_id").is_some() {
                        vec!["me", "calendars", calendar, "events"]
                    } else {
                        vec!["me", "events"]
                    }
                }
            };
            if !event_id.is_empty() {
                segments.push(event_id);
            }
            path(&self.calendar, &segments)?
        } else {
            match self.provider {
                Provider::Microsoft365 => {
                    if contact_id.is_empty() {
                        path(&self.contacts, &["me", "contacts"])?
                    } else {
                        path(&self.contacts, &["me", "contacts", contact_id])?
                    }
                }
                Provider::Google => match name {
                    "contacts_list" => path(&self.contacts, &["people", "me", "connections"])?,
                    "contacts_create" => path(&self.contacts, &["people:createContact"])?,
                    "contacts_update" | "contacts_delete" => {
                        let id = contact_id
                            .strip_prefix("people/")
                            .ok_or("invalid_contact_id")?;
                        let suffix = if name == "contacts_update" {
                            "updateContact"
                        } else {
                            "deleteContact"
                        };
                        path(&self.contacts, &["people", &format!("{id}:{suffix}")])?
                    }
                    _ => return Err("unknown_tool"),
                },
            }
        };
        if read {
            let mut query = url.query_pairs_mut();
            if self.provider == Provider::Microsoft365 {
                query.append_pair("$top", &limit);
            } else if name == "contacts_list" {
                query
                    .append_pair("pageSize", &limit)
                    .append_pair("personFields", "names,emailAddresses,phoneNumbers");
            } else {
                query.append_pair("maxResults", &limit);
            }
            if let Some(page) = args.get("page_token").and_then(Value::as_str) {
                // Graph continuation URLs are never fetched: only an opaque skip token is accepted.
                query.append_pair(
                    if self.provider == Provider::Microsoft365 {
                        "$skiptoken"
                    } else {
                        "pageToken"
                    },
                    page,
                );
            }
            if name == "calendar_list" {
                if let (Some(start), Some(end)) = (
                    args.get("start").and_then(Value::as_str),
                    args.get("end").and_then(Value::as_str),
                ) {
                    if self.provider == Provider::Google {
                        query
                            .append_pair("timeMin", start)
                            .append_pair("timeMax", end);
                    } else {
                        query.append_pair(
                            "$filter",
                            &format!(
                                "start/dateTime ge '{}' and end/dateTime le '{}'",
                                odata_literal(start),
                                odata_literal(end)
                            ),
                        );
                    }
                } else if args.get("start").is_some() || args.get("end").is_some() {
                    return Err("date_range_incomplete");
                }
            }
        }
        let method = if read {
            Method::GET
        } else if name.ends_with("_delete") {
            Method::DELETE
        } else if name.ends_with("_update") {
            Method::PATCH
        } else {
            Method::POST
        };
        let body = if name == "calendar_create" || name == "calendar_update" {
            Some(args["event"].clone())
        } else if name == "contacts_create" || name == "contacts_update" {
            let contact = &args["contact"];
            let mut body = json!({});
            match self.provider {
                Provider::Microsoft365 => {
                    if let Some(v) = contact.get("given_name") {
                        body["givenName"] = v.clone();
                    }
                    if let Some(v) = contact.get("family_name") {
                        body["surname"] = v.clone();
                    }
                    if let Some(v) = contact.get("email_address") {
                        body["emailAddresses"] = json!([{"address":v}]);
                    }
                    if let Some(v) = contact.get("phone_number") {
                        body["businessPhones"] = json!([v]);
                    }
                }
                Provider::Google => {
                    if contact.get("given_name").is_some() || contact.get("family_name").is_some() {
                        body["names"] = json!([{"givenName":contact.get("given_name").unwrap_or(&json!("")),"familyName":contact.get("family_name").unwrap_or(&json!(""))}]);
                    }
                    if let Some(v) = contact.get("email_address") {
                        body["emailAddresses"] = json!([{"value":v}]);
                    }
                    if let Some(v) = contact.get("phone_number") {
                        body["phoneNumbers"] = json!([{"value":v}]);
                    }
                    if name == "contacts_update" {
                        body["etag"] = args["etag"].clone();
                        let fields = body
                            .as_object()
                            .ok_or("invalid_contact")?
                            .keys()
                            .filter(|key| key.as_str() != "etag")
                            .cloned()
                            .collect::<Vec<_>>()
                            .join(",");
                        url.query_pairs_mut()
                            .append_pair("updatePersonFields", &fields);
                    }
                }
            }
            Some(body)
        } else {
            None
        };
        Ok((method, url, body))
    }
}
fn path(base: &Url, segments: &[&str]) -> Result<Url, &'static str> {
    if segments
        .iter()
        .any(|part| part.is_empty() || matches!(*part, "." | "..") || part.contains('/'))
    {
        return Err("invalid_resource_id");
    }
    let mut url = base.clone();
    url.path_segments_mut()
        .map_err(|_| "invalid_origin")?
        .pop_if_empty()
        .extend(segments);
    Ok(url)
}
fn odata_literal(value: &str) -> String {
    value.replace('\'', "''")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_origin_and_identifier_encoding_prevent_endpoint_injection() {
        for provider in [Provider::Google, Provider::Microsoft365] {
            let client = Connector::new(provider, "fixture".into()).unwrap();
            let (_, url, _) = client
                .request(
                    "calendar_create",
                    &json!({"calendar_id":"a?b#c","event":{"summary":"test"}}),
                )
                .unwrap();
            assert!(url.query().is_none());
            assert!(url.fragment().is_none());
            assert!(client
                .request("calendar_delete", &json!({"event_id":"../../external"}))
                .is_err());
        }
    }
    #[test]
    fn contacts_updates_preserve_provider_concurrency_contract() {
        let client = Connector::new(Provider::Google, "fixture".into()).unwrap();
        let (method,url,body)=client.request("contacts_update",&json!({"contact_id":"people/id","etag":"revision","contact":{"email_address":"test@example.invalid"}})).unwrap();
        assert_eq!(method, Method::PATCH);
        assert!(url.as_str().contains("updateContact"));
        assert_eq!(body.unwrap()["etag"], "revision");
        assert!(url.as_str().contains("updatePersonFields=emailAddresses"));
        let client = Connector::new(Provider::Microsoft365, "fixture".into()).unwrap();
        let (_,_,body)=client.request("contacts_update",&json!({"contact_id":"id","etag":"revision","contact":{"email_address":"test@example.invalid"}})).unwrap();
        assert!(body.as_ref().unwrap().get("givenName").is_none());
    }
    #[tokio::test]
    async fn missing_oauth_and_unknown_arguments_fail_before_network() {
        let client = Connector::new(Provider::Google, String::new()).unwrap();
        assert_eq!(
            client.call("calendar_list", &json!({})).await.unwrap_err(),
            "oauth_required"
        );
        assert_eq!(
            client
                .call(
                    "calendar_list",
                    &json!({"endpoint":"https://example.invalid"})
                )
                .await
                .unwrap_err(),
            "invalid_arguments"
        );
    }
    #[tokio::test]
    async fn real_http_contact_patch_binds_etag_and_uses_private_bearer_header() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint =
            Url::parse(&format!("http://{}/v1.0/", listener.local_addr().unwrap())).unwrap();
        let task = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut bytes = vec![0; 8192];
            let count = stream.read(&mut bytes).await.unwrap();
            let request = String::from_utf8(bytes[..count].to_vec())
                .unwrap()
                .to_lowercase();
            assert!(request.starts_with("patch /v1.0/me/contacts/contact-1 http/1.1"));
            assert!(request.contains("if-match: revision-2"));
            assert!(request.contains("authorization: bearer fixture-only"));
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}").await.unwrap();
        });
        let mut connector = Connector::new(Provider::Microsoft365, "fixture-only".into()).unwrap();
        connector.contacts = endpoint;
        let result=connector.call("contacts_update",&json!({"contact_id":"contact-1","etag":"revision-2","contact":{"given_name":"Test"}})).await.unwrap();
        assert_eq!(result["ok"], true);
        task.await.unwrap();
    }
    #[tokio::test]
    async fn lost_mutation_response_is_unknown_without_network_retry() {
        use tokio::io::AsyncReadExt;
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint =
            Url::parse(&format!("http://{}/v1.0/", listener.local_addr().unwrap())).unwrap();
        let task = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut bytes = [0; 8192];
            stream.read(&mut bytes).await.unwrap();
            drop(stream);
            assert!(
                tokio::time::timeout(std::time::Duration::from_millis(100), listener.accept())
                    .await
                    .is_err()
            );
        });
        let mut connector = Connector::new(Provider::Microsoft365, "fixture-only".into()).unwrap();
        connector.calendar = endpoint;
        assert_eq!(
            connector
                .call("calendar_create", &json!({"event":{"subject":"Fixture"}}))
                .await
                .unwrap_err(),
            "action_outcome_unknown"
        );
        task.await.unwrap();
    }
}
