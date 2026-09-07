//! `syn`-based fail-closed contract completeness scanner for Rust V2 modules.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use proc_macro2::Span;
use serde::{Deserialize, Serialize};
use syn::{
    spanned::Spanned,
    visit::{self, Visit},
    Block, Expr, ExprCall, ExprMethodCall, FnArg, ImplItem, Item, Lit, Pat, Signature, Type,
};

const CONTEXT_METHODS: [&str; 4] = ["provide", "require", "on", "dispatch"];

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScanRequestV2 {
    pub source: String,
    pub entrypoint: String,
    pub declarations: BTreeMap<String, BTreeSet<String>>,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct ScanIssueV2 {
    pub code: &'static str,
    pub line: Option<usize>,
    pub detail: String,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct ScanResponseV2 {
    pub issues: Vec<ScanIssueV2>,
}

struct FunctionV2<'a> {
    signature: &'a Signature,
    block: &'a Block,
}

#[must_use]
pub fn scan_rust_contract_v2(request: &ScanRequestV2) -> ScanResponseV2 {
    let file = match syn::parse_file(&request.source) {
        Ok(file) => file,
        Err(error) => {
            return ScanResponseV2 {
                issues: vec![ScanIssueV2 {
                    code: "rust_source_invalid",
                    line: span_line(error.span()),
                    detail: error.to_string(),
                }],
            };
        }
    };
    let functions = collect_functions(&file.items);
    let constants = collect_constants(&file.items);
    let entrypoint = match resolve_entrypoint(&request.entrypoint, &functions) {
        Ok(entrypoint) => entrypoint,
        Err(issue) => {
            return ScanResponseV2 {
                issues: vec![issue],
            }
        }
    };
    let entrypoint_function = functions
        .get(&entrypoint)
        .expect("resolved Rust entrypoint must exist in the source index");
    if context_parameter_names(entrypoint_function.signature).is_empty() {
        return ScanResponseV2 {
            issues: vec![ScanIssueV2 {
                code: "unclassified_entrypoint_context",
                line: span_line(entrypoint_function.signature.span()),
                detail: "Rust entrypoint has no typed ContextV2 parameter".to_owned(),
            }],
        };
    }

    let mut issues = Vec::new();
    let mut pending = VecDeque::from([entrypoint]);
    let mut visited = BTreeSet::new();
    while let Some(name) = pending.pop_front() {
        if !visited.insert(name.clone()) {
            continue;
        }
        let function = functions
            .get(&name)
            .expect("queued Rust function must exist in the source index");
        let context_names = context_parameter_names(function.signature);
        let mut scanner = ContextCallScannerV2 {
            context_names: &context_names,
            constants: &constants,
            declarations: &request.declarations,
            functions: &functions,
            referenced_functions: BTreeSet::new(),
            issues: Vec::new(),
        };
        scanner.visit_block(function.block);
        pending.extend(scanner.referenced_functions);
        issues.extend(scanner.issues);
    }
    issues.sort_by(|left, right| {
        (left.line.unwrap_or_default(), left.code, &left.detail).cmp(&(
            right.line.unwrap_or_default(),
            right.code,
            &right.detail,
        ))
    });
    ScanResponseV2 { issues }
}

fn collect_functions(items: &[Item]) -> BTreeMap<String, FunctionV2<'_>> {
    let mut functions = BTreeMap::new();
    for item in items {
        match item {
            Item::Fn(function) => {
                functions.insert(
                    function.sig.ident.to_string(),
                    FunctionV2 {
                        signature: &function.sig,
                        block: &function.block,
                    },
                );
            }
            Item::Impl(item_impl) => {
                let Some(owner) = impl_type_name(&item_impl.self_ty) else {
                    continue;
                };
                for impl_item in &item_impl.items {
                    let ImplItem::Fn(method) = impl_item else {
                        continue;
                    };
                    functions.insert(
                        format!("{owner}::{}", method.sig.ident),
                        FunctionV2 {
                            signature: &method.sig,
                            block: &method.block,
                        },
                    );
                }
            }
            _ => {}
        }
    }
    functions
}

fn collect_constants(items: &[Item]) -> BTreeMap<String, String> {
    items
        .iter()
        .filter_map(|item| {
            let Item::Const(constant) = item else {
                return None;
            };
            literal_string(&constant.expr).map(|value| (constant.ident.to_string(), value))
        })
        .collect()
}

fn impl_type_name(value: &Type) -> Option<String> {
    let Type::Path(path) = value else {
        return None;
    };
    path.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
}

fn resolve_entrypoint(
    entrypoint: &str,
    functions: &BTreeMap<String, FunctionV2<'_>>,
) -> Result<String, ScanIssueV2> {
    let parts: Vec<_> = entrypoint
        .split([':', '#', '.'])
        .filter(|part| !part.is_empty())
        .collect();
    let symbol = parts.last().copied().unwrap_or(entrypoint);
    let qualified = (parts.len() >= 2).then(|| format!("{}::{symbol}", parts[parts.len() - 2]));
    let exact = entrypoint.replace(['#', '.'], "::");
    for candidate in [Some(exact), qualified, Some(symbol.to_owned())]
        .into_iter()
        .flatten()
    {
        if functions.contains_key(&candidate) {
            return Ok(candidate);
        }
    }
    let suffix = format!("::{symbol}");
    let mut matches = functions
        .keys()
        .filter(|name| name.ends_with(&suffix))
        .cloned();
    let Some(candidate) = matches.next() else {
        return Err(ScanIssueV2 {
            code: "entrypoint_missing",
            line: None,
            detail: format!("Rust entrypoint function is not defined: {entrypoint}"),
        });
    };
    if matches.next().is_some() {
        return Err(ScanIssueV2 {
            code: "unclassified_entrypoint_apply",
            line: None,
            detail: format!("Rust entrypoint function is ambiguous: {entrypoint}"),
        });
    }
    Ok(candidate)
}

struct ContextCallScannerV2<'a> {
    context_names: &'a BTreeSet<String>,
    constants: &'a BTreeMap<String, String>,
    declarations: &'a BTreeMap<String, BTreeSet<String>>,
    functions: &'a BTreeMap<String, FunctionV2<'a>>,
    referenced_functions: BTreeSet<String>,
    issues: Vec<ScanIssueV2>,
}

impl Visit<'_> for ContextCallScannerV2<'_> {
    fn visit_expr_method_call(&mut self, call: &ExprMethodCall) {
        let method = call.method.to_string();
        if CONTEXT_METHODS.contains(&method.as_str()) && self.is_context_receiver(&call.receiver) {
            let key = call
                .args
                .first()
                .and_then(|argument| self.static_key(argument));
            match key {
                None => self.issues.push(ScanIssueV2 {
                    code: "unclassified_context_call",
                    line: span_line(call.span()),
                    detail: format!("context.{method} requires a literal string declaration key"),
                }),
                Some(value)
                    if !self
                        .declarations
                        .get(&method)
                        .is_some_and(|declared| declared.contains(&value)) =>
                {
                    self.issues.push(ScanIssueV2 {
                        code: "undeclared_context_call",
                        line: span_line(call.span()),
                        detail: format!(
                            "context.{method} {value} is absent from the module contract"
                        ),
                    });
                }
                Some(_) => {}
            }
        }
        visit::visit_expr_method_call(self, call);
    }

    fn visit_expr_call(&mut self, call: &ExprCall) {
        if let Expr::Path(path) = call.func.as_ref() {
            if let Some(name) = path
                .path
                .segments
                .last()
                .map(|segment| segment.ident.to_string())
            {
                if self.functions.contains_key(&name) {
                    self.referenced_functions.insert(name);
                }
            }
        }
        visit::visit_expr_call(self, call);
    }
}

impl ContextCallScannerV2<'_> {
    fn is_context_receiver(&self, receiver: &Expr) -> bool {
        let Expr::Path(path) = receiver else {
            return false;
        };
        path.path
            .get_ident()
            .is_some_and(|ident| self.context_names.contains(&ident.to_string()))
    }

    fn static_key(&self, expression: &Expr) -> Option<String> {
        literal_string(expression).or_else(|| {
            let Expr::Path(path) = expression else {
                return None;
            };
            path.path
                .get_ident()
                .and_then(|ident| self.constants.get(&ident.to_string()).cloned())
        })
    }
}

fn context_parameter_names(signature: &Signature) -> BTreeSet<String> {
    signature
        .inputs
        .iter()
        .filter_map(|argument| {
            let FnArg::Typed(argument) = argument else {
                return None;
            };
            if !type_is_context(&argument.ty) {
                return None;
            }
            let Pat::Ident(pattern) = argument.pat.as_ref() else {
                return None;
            };
            Some(pattern.ident.to_string())
        })
        .collect()
}

fn type_is_context(value: &Type) -> bool {
    match value {
        Type::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "ContextV2"),
        Type::Reference(reference) => type_is_context(&reference.elem),
        Type::Paren(parenthesized) => type_is_context(&parenthesized.elem),
        Type::Group(group) => type_is_context(&group.elem),
        _ => false,
    }
}

fn literal_string(expression: &Expr) -> Option<String> {
    let Expr::Lit(literal) = expression else {
        return None;
    };
    let Lit::Str(value) = &literal.lit else {
        return None;
    };
    Some(value.value())
}

fn span_line(span: Span) -> Option<usize> {
    let line = span.start().line;
    (line > 0).then_some(line)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request(source: &str, declarations: &[(&str, &[&str])]) -> ScanRequestV2 {
        ScanRequestV2 {
            source: source.to_owned(),
            entrypoint: "example::apply".to_owned(),
            declarations: declarations
                .iter()
                .map(|(method, values)| {
                    (
                        (*method).to_owned(),
                        values.iter().map(|value| (*value).to_owned()).collect(),
                    )
                })
                .collect(),
        }
    }

    #[test]
    fn declared_literal_and_constant_calls_are_complete() {
        let result = scan_rust_contract_v2(&request(
            r#"
const CLOCK: &str = "service:clock";
fn apply(context: &mut ContextV2) {
    context.provide(CLOCK, ());
    context.require::<()>("database");
}
"#,
            &[("provide", &["service:clock"]), ("require", &["database"])],
        ));

        assert_eq!(result, ScanResponseV2 { issues: vec![] });
    }

    #[test]
    fn dynamic_key_is_unclassified() {
        let result = scan_rust_contract_v2(&request(
            r#"
fn apply(context: &mut ContextV2) {
    let service = "service:clock";
    context.provide(service, ());
}
"#,
            &[("provide", &["service:clock"])],
        ));

        assert_eq!(result.issues[0].code, "unclassified_context_call");
    }

    #[test]
    fn undeclared_literal_is_rejected() {
        let result = scan_rust_contract_v2(&request(
            r#"
fn apply(context: &mut ContextV2) {
    context.dispatch("event:other", ());
}
"#,
            &[("dispatch", &["event:declared"])],
        ));

        assert_eq!(result.issues[0].code, "undeclared_context_call");
    }

    #[test]
    fn entrypoint_without_typed_context_is_rejected() {
        let result =
            scan_rust_contract_v2(&request("fn apply(_context: &mut OtherContext) {}", &[]));

        assert_eq!(result.issues[0].code, "unclassified_entrypoint_context");
    }

    #[test]
    fn qualified_impl_entrypoint_selects_exact_owner() {
        let mut scan_request = request(
            r#"
struct PluginA;
struct PluginB;

impl PluginA {
    fn apply(context: &mut ContextV2) {
        context.provide("service:wrong", ());
    }
}

impl PluginB {
    fn apply(_context: &mut ContextV2) {}
}
"#,
            &[],
        );
        scan_request.entrypoint = "PluginB::apply".to_owned();

        assert_eq!(
            scan_rust_contract_v2(&scan_request),
            ScanResponseV2 { issues: vec![] }
        );
    }
}
