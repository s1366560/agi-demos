//! Structural decoding of the user-visible portion of a streamed agent action.

/// Incrementally emits only the top-level `answer` of a `kind: finish` action.
/// Tool arguments and reasoning wrappers are never forwarded to the caller.
#[derive(Default)]
pub struct AgentAnswerStream {
    buffer: String,
    emitted: usize,
}

impl AgentAnswerStream {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn has_emitted(&self) -> bool {
        self.emitted > 0
    }

    pub fn push(&mut self, fragment: &str, on_text: &(dyn Fn(&str) + Send + Sync)) {
        self.buffer.push_str(fragment);
        if let Some(answer) = answer_prefix(&self.buffer) {
            if answer.len() > self.emitted {
                on_text(&answer[self.emitted..]);
                self.emitted = answer.len();
            }
        }
    }
}

fn answer_prefix(buffer: &str) -> Option<String> {
    let mut source = buffer.trim_start();
    if let Some(reasoning) = source.strip_prefix("<think>") {
        source = reasoning.split_once("</think>")?.1.trim_start();
    }
    if let Some(fence) = source.strip_prefix("```") {
        source = fence.split_once('\n')?.1.trim_start();
    }
    source = source.strip_prefix('{')?;
    let mut finish = false;
    let mut answer = None;
    loop {
        source = source.trim_start();
        let (key, used, complete) = string_prefix(source)?;
        if !complete {
            break;
        }
        source = source[used..].trim_start().strip_prefix(':')?.trim_start();
        if key == "answer" {
            let (value, used, complete) = string_prefix(source)?;
            answer = Some(value);
            if !complete {
                break;
            }
            source = &source[used..];
        } else {
            let mut values =
                serde_json::Deserializer::from_str(source).into_iter::<serde_json::Value>();
            let Some(Ok(value)) = values.next() else {
                break;
            };
            if key == "kind" {
                finish = value.as_str() == Some("finish");
            }
            source = &source[values.byte_offset()..];
        }
        source = source.trim_start();
        if let Some(rest) = source.strip_prefix(',') {
            source = rest;
        } else {
            break;
        }
    }
    finish.then_some(answer).flatten()
}

// Return the decoded prefix, consumed bytes, and whether the closing quote arrived.
// Escapes are decoded by serde_json; incomplete escapes (including UTF-16 surrogate
// pairs) stay buffered until the next fragment rather than leaking wire syntax.
fn string_prefix(source: &str) -> Option<(String, usize, bool)> {
    source.strip_prefix('"')?;
    let mut end = 1;
    let mut complete = false;
    while end < source.len() {
        let ch = source[end..].chars().next()?;
        if ch == '"' {
            complete = true;
            break;
        }
        if ch == '\\' {
            let escape = *source.as_bytes().get(end + 1)?;
            let mut len = if escape == b'u' { 6 } else { 2 };
            let Some(mut encoded) = source.get(end..end + len) else {
                break;
            };
            if serde_json::from_str::<String>(&format!("\"{encoded}\"")).is_err() {
                if escape != b'u' {
                    break;
                }
                len = 12;
                let Some(pair) = source.get(end..end + len) else {
                    break;
                };
                encoded = pair;
                if serde_json::from_str::<String>(&format!("\"{encoded}\"")).is_err() {
                    break;
                }
            }
            end += len;
        } else if ch.is_control() {
            break;
        } else {
            end += ch.len_utf8();
        }
    }
    let decoded = serde_json::from_str::<String>(&format!("{}\"", &source[..end])).ok()?;
    Some((decoded, end + usize::from(complete), complete))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[test]
    fn decodes_every_fragment_boundary_without_wire_syntax() {
        let source = r#"{"kind":"finish","answer":"hello \"world\"\n你好 \uD83D\uDE00!"}"#;
        let expected = "hello \"world\"\n你好 😀!";
        for boundary in source.char_indices().map(|(index, _)| index) {
            let output = Mutex::new(String::new());
            let emit = |text: &str| output.lock().unwrap().push_str(text);
            let mut stream = AgentAnswerStream::new();
            stream.push(&source[..boundary], &emit);
            stream.push(&source[boundary..], &emit);
            assert_eq!(*output.lock().unwrap(), expected, "boundary {boundary}");
        }
    }

    #[test]
    fn emits_incomplete_answer_but_never_tools_or_reasoning() {
        let output = Mutex::new(String::new());
        let emit = |text: &str| output.lock().unwrap().push_str(text);
        let mut stream = AgentAnswerStream::new();
        stream.push("<think>{\"kind\":\"finish\",\"answer\":\"private\"}", &emit);
        assert!(output.lock().unwrap().is_empty());
        stream.push(
            "</think>\n```json\n{\"kind\":\"finish\",\"answer\":\"Hello ",
            &emit,
        );
        assert_eq!(*output.lock().unwrap(), "Hello ");
        stream.push("world\"}\n```", &emit);
        assert_eq!(*output.lock().unwrap(), "Hello world");
        let mut tool = AgentAnswerStream::new();
        tool.push(
            r#"{"kind":"call_tool","input_json":{"kind":"finish","answer":"private"}}"#,
            &emit,
        );
        assert_eq!(*output.lock().unwrap(), "Hello world");
    }

    #[test]
    fn waits_for_finish_kind_when_answer_comes_first() {
        let output = Mutex::new(String::new());
        let emit = |text: &str| output.lock().unwrap().push_str(text);
        let mut stream = AgentAnswerStream::new();
        stream.push(r#"{"answer":"Hello","kind":"fi"#, &emit);
        assert!(output.lock().unwrap().is_empty());
        stream.push("nish\"}", &emit);
        assert_eq!(*output.lock().unwrap(), "Hello");
    }
}
