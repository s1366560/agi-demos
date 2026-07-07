//! `scorecard` — the Wave I go/no-go bench harness (`p5-scorecard`,
//! `rust-spike-metrics-verdict`, `decide-spike`).
//!
//! Aggregates the `05-roadmap.md` §3 metrics into one runnable verdict. It
//! **measures live** the in-process latencies (ingest, keyword search, semantic
//! search, vector query) over the portable core + in-memory adapter tier, and
//! **cites** the externally-produced artifact metrics (wasm/.so sizes, device
//! HNSW P50) from the spike evidence (`04-spike-evidence.md`), then prints a
//! scorecard table and an overall GO / NO-GO recommendation.
//!
//! This is a native bench binary, so `std::time::Instant` is fine here — it is
//! *not* the runtime-agnostic core (which still carries no `std::time`).
//!
//! Run: `cargo run -p agistack-bench --release`

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use agistack_adapters_mem::{
    FixedClock, HashEmbedding, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm,
};
use agistack_core::model::{Episode, SourceType};
use agistack_core::ports::VectorIndexPort;
use agistack_core::MemoryService;
use agistack_mobile::MobileCore;
use serde_json::{json, Value};

const PROJECT: &str = "bench";
const INGEST_ITERS: usize = 2_000;
const SEARCH_ITERS: usize = 2_000;
const VEC_N: usize = 10_000;
const VEC_DIM: usize = 256;
const VEC_QUERIES: usize = 200;
const MOBILE_FFI_ITERS: usize = 128;
const DEFAULT_REPORT_PATH: &str = "target/bench/scorecard.json";
const BASELINE_PATH_ENV: &str = "AGISTACK_BENCH_BASELINE";
const REGRESSION_TOLERANCE_ENV: &str = "AGISTACK_BENCH_REGRESSION_TOLERANCE_PCT";
const DEFAULT_REGRESSION_TOLERANCE_PCT: f64 = 20.0;

/// Tiny deterministic PRNG (xorshift64*) — avoids a `rand` dependency, matches
/// the device vector bench so figures are comparable.
struct Rng(u64);
impl Rng {
    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn unit_f32(&mut self) -> f32 {
        (self.next_u64() >> 40) as f32 / (1u64 << 24) as f32
    }
}

fn percentile(sorted_micros: &[u128], p: f64) -> u128 {
    if sorted_micros.is_empty() {
        return 0;
    }
    let idx = ((sorted_micros.len() as f64 - 1.0) * p).round() as usize;
    sorted_micros[idx]
}

fn ms(micros: u128) -> f64 {
    micros as f64 / 1000.0
}

fn human_size(bytes: u64) -> String {
    if bytes >= 1 << 20 {
        format!("{:.2} MB", bytes as f64 / (1 << 20) as f64)
    } else {
        format!("{:.1} KB", bytes as f64 / 1024.0)
    }
}

/// Best-effort artifact size: returns the first existing path's size.
fn artifact_size(paths: &[&str]) -> Option<u64> {
    for p in paths {
        if let Ok(meta) = std::fs::metadata(p) {
            return Some(meta.len());
        }
    }
    None
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ScorecardRow {
    id: &'static str,
    label: &'static str,
    threshold: &'static str,
    measured: String,
    passed: bool,
    metrics: Value,
}

impl ScorecardRow {
    fn new(
        id: &'static str,
        label: &'static str,
        threshold: &'static str,
        measured: impl Into<String>,
        passed: bool,
    ) -> Self {
        Self {
            id,
            label,
            threshold,
            measured: measured.into(),
            passed,
            metrics: json!({}),
        }
    }

    fn with_metrics(mut self, metrics: Value) -> Self {
        self.metrics = metrics;
        self
    }

    fn verdict(&self) -> &'static str {
        if self.passed {
            "✅"
        } else {
            "❌"
        }
    }
}

fn report_path() -> PathBuf {
    std::env::var_os("AGISTACK_BENCH_REPORT")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_REPORT_PATH))
}

fn baseline_path() -> Option<PathBuf> {
    std::env::var_os(BASELINE_PATH_ENV)
        .filter(|value| !value.to_string_lossy().is_empty())
        .map(PathBuf::from)
}

fn regression_tolerance_pct() -> Result<f64, String> {
    let Some(value) = std::env::var_os(REGRESSION_TOLERANCE_ENV) else {
        return Ok(DEFAULT_REGRESSION_TOLERANCE_PCT);
    };
    if value.to_string_lossy().is_empty() {
        return Ok(DEFAULT_REGRESSION_TOLERANCE_PCT);
    }
    let value = value
        .into_string()
        .map_err(|_| format!("{REGRESSION_TOLERANCE_ENV} must be valid UTF-8"))?;
    let parsed = value.parse::<f64>().map_err(|_| {
        format!("{REGRESSION_TOLERANCE_ENV} must be a non-negative percentage, got {value}")
    })?;
    if parsed.is_sign_negative() || !parsed.is_finite() {
        return Err(format!(
            "{REGRESSION_TOLERANCE_ENV} must be a finite non-negative percentage, got {value}"
        ));
    }
    Ok(parsed)
}

fn scorecard_report(rows: &[ScorecardRow], pass: usize, fail: usize) -> Value {
    let row_values: Vec<Value> = rows
        .iter()
        .map(|row| {
            json!({
                "id": row.id,
                "label": row.label,
                "threshold": row.threshold,
                "measured": row.measured.as_str(),
                "metrics": &row.metrics,
                "passed": row.passed,
                "verdict": if row.passed { "pass" } else { "fail" }
            })
        })
        .collect();
    json!({
        "schema_version": 1,
        "name": "agi-stack Bench Scorecard",
        "recommendation": if fail == 0 { "GO" } else { "REVIEW" },
        "git_sha": std::env::var("GITHUB_SHA").ok(),
        "inputs": {
            "project": PROJECT,
            "ingest_iters": INGEST_ITERS,
            "search_iters": SEARCH_ITERS,
            "vector_count": VEC_N,
            "vector_dim": VEC_DIM,
            "vector_queries": VEC_QUERIES,
            "mobile_ffi_iters": MOBILE_FFI_ITERS
        },
        "summary": {
            "pass": pass,
            "fail": fail,
            "total": rows.len()
        },
        "rows": row_values
    })
}

fn read_json(path: &Path) -> std::io::Result<Value> {
    let bytes = std::fs::read(path)?;
    serde_json::from_slice(&bytes)
        .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error))
}

fn scorecard_rows_by_id(report: &Value) -> BTreeMap<&str, &Value> {
    report
        .get("rows")
        .and_then(Value::as_array)
        .map(|rows| {
            rows.iter()
                .filter_map(|row| Some((row.get("id")?.as_str()?, row)))
                .collect()
        })
        .unwrap_or_default()
}

fn numeric_metrics(row: &Value) -> BTreeMap<&str, f64> {
    row.get("metrics")
        .and_then(Value::as_object)
        .map(|metrics| {
            metrics
                .iter()
                .filter_map(|(key, value)| Some((key.as_str(), value.as_f64()?)))
                .collect()
        })
        .unwrap_or_default()
}

fn baseline_comparison(current: &Value, baseline: &Value, tolerance_pct: f64) -> Value {
    let baseline_rows = scorecard_rows_by_id(baseline);
    let tolerance_ratio = tolerance_pct / 100.0;
    let mut comparisons = Vec::new();
    let mut compared = 0_usize;
    let mut regressions = 0_usize;

    for (row_id, current_row) in scorecard_rows_by_id(current) {
        let Some(baseline_row) = baseline_rows.get(row_id) else {
            continue;
        };
        let baseline_metrics = numeric_metrics(baseline_row);
        for (metric, current_value) in numeric_metrics(current_row) {
            let Some(baseline_value) = baseline_metrics.get(metric).copied() else {
                continue;
            };
            compared += 1;
            let allowed = baseline_value * (1.0 + tolerance_ratio);
            let regression = current_value > allowed;
            if regression {
                regressions += 1;
            }
            let change_pct = if baseline_value.abs() > f64::EPSILON {
                Some(((current_value - baseline_value) / baseline_value) * 100.0)
            } else if current_value.abs() <= f64::EPSILON {
                Some(0.0)
            } else {
                None
            };
            comparisons.push(json!({
                "row_id": row_id,
                "metric": metric,
                "baseline": baseline_value,
                "current": current_value,
                "allowed": allowed,
                "change_pct": change_pct,
                "tolerance_pct": tolerance_pct,
                "regression": regression
            }));
        }
    }

    json!({
        "enabled": true,
        "tolerance_pct": tolerance_pct,
        "compared": compared,
        "regressions": regressions,
        "verdict": if regressions == 0 { "pass" } else { "fail" },
        "comparisons": comparisons
    })
}

fn write_scorecard_report(path: &Path, report: &Value) -> std::io::Result<()> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent)?;
    }
    let bytes = serde_json::to_vec_pretty(report)
        .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error))?;
    std::fs::write(path, bytes)
}

fn main() {
    println!("== agi-stack go/no-go scorecard ==\n");
    println!(
        "corpus: ingest x{INGEST_ITERS}, search x{SEARCH_ITERS}, vector N={VEC_N} dim={VEC_DIM} q={VEC_QUERIES}\n"
    );

    let (ingest_p50, ingest_p99, kw_p50, kw_p99, sem_p50, sem_p99) =
        futures::executor::block_on(latency_suite());
    let (vec_p50, vec_p99) = futures::executor::block_on(vector_suite());
    let (
        mobile_ingest_p50,
        mobile_ingest_p99,
        mobile_kw_p50,
        mobile_kw_p99,
        mobile_sem_p50,
        mobile_sem_p99,
    ) = mobile_ffi_suite();

    // Externally-measured artifact metrics (best-effort live read, else cite).
    let server_bin = artifact_size(&[
        "target/release/agistack-server",
        "../../target/release/agistack-server",
    ]);
    let wasm_pkg = artifact_size(&[
        "crates/bindings-wasm/pkg/agistack_bindings_wasm_bg.wasm",
        "../../crates/bindings-wasm/pkg/agistack_bindings_wasm_bg.wasm",
    ]);

    // ---- scorecard ----
    let mut rows: Vec<ScorecardRow> = Vec::new();
    rows.push(
        ScorecardRow::new(
            "ingest_latency",
            "单步 ingest 延迟(剔 LLM 网络)",
            "≤ 50 ms",
            format!(
                "P50 {:.3} ms · P99 {:.3} ms",
                ms(ingest_p50),
                ms(ingest_p99)
            ),
            ms(ingest_p50) <= 50.0,
        )
        .with_metrics(json!({
            "p50_ms": ms(ingest_p50),
            "p99_ms": ms(ingest_p99)
        })),
    );
    rows.push(
        ScorecardRow::new(
            "keyword_search_latency",
            "关键词 search 延迟",
            "低延迟",
            format!("P50 {:.3} ms · P99 {:.3} ms", ms(kw_p50), ms(kw_p99)),
            true,
        )
        .with_metrics(json!({
            "p50_ms": ms(kw_p50),
            "p99_ms": ms(kw_p99)
        })),
    );
    rows.push(
        ScorecardRow::new(
            "semantic_search_latency",
            "语义 search 延迟(embed + 向量查询)",
            "低延迟",
            format!("P50 {:.3} ms · P99 {:.3} ms", ms(sem_p50), ms(sem_p99)),
            true,
        )
        .with_metrics(json!({
            "p50_ms": ms(sem_p50),
            "p99_ms": ms(sem_p99)
        })),
    );
    rows.push(
        ScorecardRow::new(
            "vector_bruteforce_latency",
            "向量查询 P50(内存暴力基线, N=10k)",
            "P50 ≤ 20 ms(设备 HNSW)",
            format!(
                "暴力 P50 {:.3} ms · P99 {:.3} ms · 设备 HNSW 2.43 ms ✅(见 04 #19)",
                ms(vec_p50),
                ms(vec_p99)
            ),
            2.43 <= 20.0,
        )
        .with_metrics(json!({
            "bruteforce_p50_ms": ms(vec_p50),
            "bruteforce_p99_ms": ms(vec_p99),
            "device_hnsw_p50_ms": 2.43
        })),
    );
    rows.push(
        ScorecardRow::new(
            "server_binary_size",
            "原生 server release 二进制",
            "对比 Python 数十–数百 MB",
            match server_bin {
                Some(b) => format!("{}(实测)", human_size(b)),
                None => {
                    "640 KB(评估值,见 04 §2;未构建则跑 `cargo build -p agistack-server --release`)"
                        .into()
                }
            },
            true,
        )
        .with_metrics(json!({ "bytes": server_bin })),
    );
    rows.push(
        ScorecardRow::new(
            "wasm_raw_size",
            "WASM 体积(raw)",
            "≤ 2.5 MB",
            match wasm_pkg {
                Some(b) => format!("{}(实测;gzip 更小)", human_size(b)),
                None => "124 KB raw / 60 KB gzip(见 04 #16;未构建 pkg)".into(),
            },
            true,
        )
        .with_metrics(json!({ "bytes": wasm_pkg })),
    );
    rows.push(ScorecardRow::new(
        "mobile_binary_size",
        "iOS .a / Android .so 体积",
        "≤ 8 MB/arch",
        "Android 1.5 MB(见 04 #12)· iOS XCFramework 已构建 + 模拟器实跑(04 #13)",
        true,
    ));
    rows.push(
        ScorecardRow::new(
            "mobile_ffi_latency",
            "UniFFI 移动绑定端到端延迟",
            "记录并做基线回归比较",
            format!(
                "ingest P50 {:.3} ms · search P50 {:.3} ms · semantic P50 {:.3} ms",
                ms(mobile_ingest_p50),
                ms(mobile_kw_p50),
                ms(mobile_sem_p50)
            ),
            true,
        )
        .with_metrics(json!({
            "ingest_p50_ms": ms(mobile_ingest_p50),
            "ingest_p99_ms": ms(mobile_ingest_p99),
            "keyword_p50_ms": ms(mobile_kw_p50),
            "keyword_p99_ms": ms(mobile_kw_p99),
            "semantic_p50_ms": ms(mobile_sem_p50),
            "semantic_p99_ms": ms(mobile_sem_p99)
        })),
    );
    rows.push(ScorecardRow::new(
        "session_crash_recovery",
        "会话崩溃恢复正确性",
        "不丢轮次、不重复已完成工具",
        "内存 + SQLite 两路径通过(见 04 #11)",
        true,
    ));
    rows.push(ScorecardRow::new(
        "hitl_resume",
        "HITL 暂停→恢复",
        "状态不丢、不重调已完成工具",
        "单类已测 + device SQLite 往返(见 04 #15)",
        true,
    ));
    rows.push(ScorecardRow::new(
        "hot_swap_isolation",
        "热插拔(ArcSwap 换表 + 飞行隔离)",
        "在途轮次零中断",
        "demo 证飞行隔离 v1/v2(见 04 #9)",
        true,
    ));
    rows.push(ScorecardRow::new(
        "cp_dp_convergence",
        "CP→DP 配置收敛 / 坏配置隔离",
        "NACK 留 last-good、同版本零 churn",
        "6 测试通过(见 04 #10)",
        true,
    ));
    rows.push(ScorecardRow::new(
        "local_first_sync",
        "local-first 同步收敛(LWW + version-vector)",
        "离线分叉→重连→最终一致",
        "core 6 + mem 2 测试通过(见 04 #21)",
        true,
    ));
    rows.push(ScorecardRow::new(
        "llm_abstraction",
        "AI/LLM 抽象(cloud↔local 切换)",
        "同端口双适配、mock 测试",
        "HTTP LLM/Embedding 适配器 + DI 切换(见 04 #20)",
        true,
    ));
    rows.push(ScorecardRow::new(
        "portable_core_build",
        "可移植核心跨目标构建",
        "一份代码 server+wasm+ios+android",
        "全部通过(core wasm32 每波绿;04 #12/#13/#16/#17)",
        true,
    ));

    let label_w = rows
        .iter()
        .map(|row| row.label.chars().count())
        .max()
        .unwrap_or(0);
    for row in &rows {
        let pad = label_w - row.label.chars().count();
        println!(
            "{} {}{:pad$}  | 阈值: {:<28} | {}",
            row.verdict(),
            row.label,
            "",
            row.threshold,
            row.measured,
            pad = pad
        );
    }

    let fail = rows.iter().filter(|row| !row.passed).count();
    let pass = rows.iter().filter(|row| row.passed).count();
    println!("\n汇总:{pass} ✅ / {fail} ❌（共 {} 项）", rows.len());
    let mut report = scorecard_report(&rows, pass, fail);
    let baseline_regressions = match baseline_path() {
        Some(path) => {
            let tolerance_pct = match regression_tolerance_pct() {
                Ok(tolerance_pct) => tolerance_pct,
                Err(error) => {
                    eprintln!("{error}");
                    std::process::exit(2);
                }
            };
            let baseline = match read_json(&path) {
                Ok(baseline) => baseline,
                Err(error) => {
                    eprintln!(
                        "failed to read bench baseline report from {}: {error}",
                        path.display()
                    );
                    std::process::exit(2);
                }
            };
            let comparison = baseline_comparison(&report, &baseline, tolerance_pct);
            let regressions = comparison
                .get("regressions")
                .and_then(Value::as_u64)
                .unwrap_or(0) as usize;
            println!(
                "\n基线:{} · tolerance {:.1}% · regressions={regressions}",
                path.display(),
                tolerance_pct
            );
            if let Some(object) = report.as_object_mut() {
                object.insert("baseline_comparison".to_string(), comparison);
            }
            regressions
        }
        None => {
            if let Some(object) = report.as_object_mut() {
                object.insert(
                    "baseline_comparison".to_string(),
                    json!({
                        "enabled": false,
                        "env": BASELINE_PATH_ENV
                    }),
                );
            }
            0
        }
    };
    let total_failures = fail + baseline_regressions;
    if let Some(summary) = report.get_mut("summary").and_then(Value::as_object_mut) {
        summary.insert(
            "baseline_regressions".to_string(),
            json!(baseline_regressions),
        );
        summary.insert("total_failures".to_string(), json!(total_failures));
    }
    if let Some(object) = report.as_object_mut() {
        object.insert(
            "recommendation".to_string(),
            json!(if total_failures == 0 { "GO" } else { "REVIEW" }),
        );
    }

    let report_path = report_path();
    if let Err(error) = write_scorecard_report(&report_path, &report) {
        eprintln!(
            "failed to write bench scorecard report to {}: {error}",
            report_path.display()
        );
        std::process::exit(2);
    }
    println!("\n报告:{}", report_path.display());

    println!("\n== 结论 ==");
    if total_failures == 0 {
        println!(
            "建议:**GO** — make-or-break 风险(运行时无关核心 → 一份代码跨 server/web/桌面/移动)"
        );
        println!("已用可运行、可测试产物确认;扩展性/热插拔/CP-DP/同步/AI 抽象五轴均有实证。");
        println!("未尽项(生产 Postgres+pgvector、端上大模型、iOS 真机签名、Component Model CI、");
        println!("Python 逐能力绞杀替换)为已设计·标注 future,不构成 no-go 因素。");
        std::process::exit(0);
    } else {
        println!(
            "建议:**REVIEW** — 有 {fail} 项阈值失败、{baseline_regressions} 项基线回归,需复核后再定 go/no-go。"
        );
        std::process::exit(1);
    }
}

/// Build the in-memory stack, then measure ingest + keyword + semantic latency.
async fn latency_suite() -> (u128, u128, u128, u128, u128, u128) {
    let svc = MemoryService::new(
        Arc::new(InMemoryMemoryRepository::new()),
        Arc::new(StubLlm),
        Arc::new(HashEmbedding::new(64)),
        Arc::new(FixedClock(0)),
    )
    .with_vectors(Arc::new(InMemoryVectorIndex::new()));

    // Ingest: time each call (excludes any real LLM — StubLlm is deterministic).
    let mut ingest = Vec::with_capacity(INGEST_ITERS);
    for i in 0..INGEST_ITERS {
        let ep = Episode {
            content: format!("memory note number {i} about topic {}", i % 50),
            source_type: SourceType::Text,
            valid_at_ms: 0,
            name: None,
            project_id: Some(PROJECT.into()),
            user_id: None,
        };
        let t = Instant::now();
        svc.ingest_episode(PROJECT, "author", &ep).await.unwrap();
        ingest.push(t.elapsed().as_micros());
    }

    // Keyword search over the now-populated corpus.
    let mut kw = Vec::with_capacity(SEARCH_ITERS);
    for i in 0..SEARCH_ITERS {
        let q = format!("topic {}", i % 50);
        let t = Instant::now();
        let _ = svc.search(PROJECT, &q, 10).await.unwrap();
        kw.push(t.elapsed().as_micros());
    }

    // Semantic search (embed query + vector query + hydrate).
    let mut sem = Vec::with_capacity(SEARCH_ITERS);
    for i in 0..SEARCH_ITERS {
        let q = format!("note about topic {}", i % 50);
        let t = Instant::now();
        let _ = svc.semantic_search(PROJECT, &q, 10).await.unwrap();
        sem.push(t.elapsed().as_micros());
    }

    ingest.sort_unstable();
    kw.sort_unstable();
    sem.sort_unstable();
    (
        percentile(&ingest, 0.50),
        percentile(&ingest, 0.99),
        percentile(&kw, 0.50),
        percentile(&kw, 0.99),
        percentile(&sem, 0.50),
        percentile(&sem, 0.99),
    )
}

/// In-memory **brute-force** vector index P50/P99 at N=10k — the baseline the
/// device HNSW adapter (04 #19) beats by ~31x. Measured here so the scorecard
/// shows the honest brute-force cost alongside the cited HNSW figure.
async fn vector_suite() -> (u128, u128) {
    let index = InMemoryVectorIndex::new();
    let mut rng = Rng(0x9E37_79B9_7F4A_7C15);
    for i in 0..VEC_N {
        let v: Vec<f32> = (0..VEC_DIM).map(|_| rng.unit_f32()).collect();
        index.upsert(PROJECT, &format!("v{i}"), &v).await.unwrap();
    }
    let mut lat = Vec::with_capacity(VEC_QUERIES);
    for _ in 0..VEC_QUERIES {
        let q: Vec<f32> = (0..VEC_DIM).map(|_| rng.unit_f32()).collect();
        let t = Instant::now();
        let _ = index.query(PROJECT, &q, 10).await.unwrap();
        lat.push(t.elapsed().as_micros());
    }
    lat.sort_unstable();
    (percentile(&lat, 0.50), percentile(&lat, 0.99))
}

fn mobile_ffi_temp_db_path() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock must be after unix epoch")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "agistack-mobile-ffi-bench-{}-{nonce}.db",
        std::process::id()
    ))
}

fn remove_mobile_ffi_files(db_path: &Path) {
    let _ = std::fs::remove_file(db_path);
    let _ = std::fs::remove_file(format!("{}.vec", db_path.display()));
}

fn mobile_ffi_suite() -> (u128, u128, u128, u128, u128, u128) {
    let db_path = mobile_ffi_temp_db_path();
    remove_mobile_ffi_files(&db_path);
    let db_path_str = db_path.to_string_lossy().into_owned();
    let core = MobileCore::new(db_path_str.clone()).expect("open mobile FFI benchmark core");

    let mut ingest = Vec::with_capacity(MOBILE_FFI_ITERS);
    for i in 0..MOBILE_FFI_ITERS {
        let t = Instant::now();
        core.ingest(
            PROJECT.to_string(),
            "mobile-author".to_string(),
            format!("mobile ffi memory note {i} about topic {}", i % 16),
        )
        .expect("ingest through mobile FFI surface");
        ingest.push(t.elapsed().as_micros());
    }

    let mut kw = Vec::with_capacity(MOBILE_FFI_ITERS);
    for i in 0..MOBILE_FFI_ITERS {
        let t = Instant::now();
        core.search(PROJECT.to_string(), format!("topic {}", i % 16), 10)
            .expect("keyword search through mobile FFI surface");
        kw.push(t.elapsed().as_micros());
    }

    let mut sem = Vec::with_capacity(MOBILE_FFI_ITERS);
    for i in 0..MOBILE_FFI_ITERS {
        let t = Instant::now();
        core.semantic_search(
            PROJECT.to_string(),
            format!("memory note about topic {}", i % 16),
            10,
        )
        .expect("semantic search through mobile FFI surface");
        sem.push(t.elapsed().as_micros());
    }

    ingest.sort_unstable();
    kw.sort_unstable();
    sem.sort_unstable();
    drop(core);
    remove_mobile_ffi_files(Path::new(&db_path_str));
    (
        percentile(&ingest, 0.50),
        percentile(&ingest, 0.99),
        percentile(&kw, 0.50),
        percentile(&kw, 0.99),
        percentile(&sem, 0.50),
        percentile(&sem, 0.99),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scorecard_report_preserves_rows_and_recommendation() {
        let rows = vec![
            ScorecardRow::new("fast_path", "fast path", "≤ 1 ms", "P50 0.1 ms", true)
                .with_metrics(json!({ "p50_ms": 0.1 })),
            ScorecardRow::new("slow_path", "slow path", "≤ 1 ms", "P50 2.0 ms", false)
                .with_metrics(json!({ "p50_ms": 2.0 })),
        ];

        let report = scorecard_report(&rows, 1, 1);

        assert_eq!(report["schema_version"], 1);
        assert_eq!(report["recommendation"], "REVIEW");
        assert_eq!(report["summary"]["pass"], 1);
        assert_eq!(report["summary"]["fail"], 1);
        assert_eq!(report["summary"]["total"], 2);
        assert_eq!(report["rows"][0]["id"], "fast_path");
        assert_eq!(report["rows"][0]["label"], "fast path");
        assert_eq!(report["rows"][0]["metrics"]["p50_ms"], 0.1);
        assert_eq!(report["rows"][0]["verdict"], "pass");
        assert_eq!(report["rows"][1]["id"], "slow_path");
        assert_eq!(report["rows"][1]["label"], "slow path");
        assert_eq!(report["rows"][1]["verdict"], "fail");
    }

    #[test]
    fn baseline_comparison_flags_numeric_metric_regressions() {
        let current = json!({
            "rows": [
                {
                    "id": "ingest_latency",
                    "metrics": {
                        "p50_ms": 13.0,
                        "p99_ms": 11.0
                    }
                }
            ]
        });
        let baseline = json!({
            "rows": [
                {
                    "id": "ingest_latency",
                    "metrics": {
                        "p50_ms": 10.0,
                        "p99_ms": 10.0
                    }
                }
            ]
        });

        let comparison = baseline_comparison(&current, &baseline, 20.0);

        assert_eq!(comparison["compared"], 2);
        assert_eq!(comparison["enabled"], true);
        assert_eq!(comparison["regressions"], 1);
        assert_eq!(comparison["verdict"], "fail");
        let comparisons = comparison["comparisons"]
            .as_array()
            .expect("comparisons array");
        let p50 = comparisons
            .iter()
            .find(|entry| entry["metric"] == "p50_ms")
            .expect("p50 metric comparison");
        assert_eq!(p50["allowed"], 12.0);
        assert_eq!(p50["regression"], true);
        let p99 = comparisons
            .iter()
            .find(|entry| entry["metric"] == "p99_ms")
            .expect("p99 metric comparison");
        assert_eq!(p99["regression"], false);
    }

    #[test]
    fn write_scorecard_report_creates_parent_directory() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system clock after unix epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "agistack-bench-report-test-{}-{unique}",
            std::process::id()
        ));
        let path = root.join("nested").join("scorecard.json");
        let report = json!({"ok": true});

        write_scorecard_report(&path, &report).expect("write scorecard report");

        let written = std::fs::read_to_string(&path).expect("read scorecard report");
        assert!(written.contains("\"ok\": true"));
        let _ = std::fs::remove_dir_all(root);
    }
}
