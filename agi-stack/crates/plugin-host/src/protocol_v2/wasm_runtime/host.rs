use super::failure;
use crate::protocol_v2::{QuotaV2, RuntimeV2Error};
use futures::channel::oneshot;
use serde_json::{json, Value};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc,
    },
    time::Duration,
};
use wasmtime::{
    Config, Engine, ExternType, Module, Store, StoreLimits, StoreLimitsBuilder, ValType,
};

pub(super) async fn blocking<T: Send + 'static>(
    work: impl FnOnce() -> Result<T, RuntimeV2Error> + Send + 'static,
) -> Result<T, RuntimeV2Error> {
    let (sender, receiver) = oneshot::channel();
    std::thread::Builder::new()
        .name("plugin-wasm-v2".into())
        .spawn(move || {
            let _ = sender.send(work());
        })
        .map_err(|_| failure("WASM worker unavailable"))?;
    receiver.await.map_err(|_| failure("WASM worker failed"))?
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    #[test]
    fn blocking_work_yields_to_the_async_caller() {
        block_on(async {
            let (sender, receiver) = mpsc::channel();
            let work = blocking(move || {
                receiver
                    .recv_timeout(Duration::from_secs(1))
                    .map_err(|_| failure("caller loop blocked"))
            });
            let caller = async move {
                sender.send(42).unwrap();
            };
            let (value, ()) = futures::join!(work, caller);
            assert_eq!(value.unwrap(), 42);
        });
    }

    #[test]
    fn epoch_deadline_interrupts_even_when_fuel_is_effectively_unbounded() {
        let bytes = wat::parse_str("(module (func (export \"score\") (param i32) (result i32) (loop $loop br $loop) i32.const 0))").unwrap();
        let host = WasmHost::compile(
            &bytes,
            Limits {
                fuel: u64::MAX,
                memory: 65536,
                wall_ms: 5,
                output_bytes: 1024,
            },
            ToolAbi::Score,
        )
        .unwrap();
        let start = std::time::Instant::now();
        assert!(host.run(b"x").is_err());
        assert!(start.elapsed() < Duration::from_secs(1));
    }
}

#[derive(Clone, Copy)]
pub(super) struct Limits {
    fuel: u64,
    memory: usize,
    wall_ms: u64,
    pub output_bytes: u64,
}
impl Limits {
    pub fn new(manifest: &QuotaV2, entry: &QuotaV2) -> Result<Self, RuntimeV2Error> {
        fn capped(a: Option<u64>, b: Option<u64>, max: u64) -> u64 {
            a.unwrap_or(max).min(b.unwrap_or(max)).min(max)
        }
        let fuel = capped(manifest.max_wasm_fuel, entry.max_wasm_fuel, 1_000_000);
        let memory = capped(
            manifest.max_wasm_memory_bytes,
            entry.max_wasm_memory_bytes,
            16 * 1024 * 1024,
        );
        let wall_ms = capped(manifest.max_wall_time_ms, entry.max_wall_time_ms, 1_000);
        let output_bytes = capped(manifest.max_output_bytes, entry.max_output_bytes, 65_536);
        let concurrency = capped(manifest.max_concurrent_calls, entry.max_concurrent_calls, 1);
        if fuel == 0 || memory < 65536 || wall_ms == 0 || output_bytes == 0 || concurrency == 0 {
            return Err(failure("invalid WASM resource limits"));
        }
        Ok(Self {
            fuel,
            memory: usize::try_from(memory).map_err(|_| failure("WASM memory size overflow"))?,
            wall_ms,
            output_bytes,
        })
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum ToolAbi {
    Score,
    Invoke,
}

impl ToolAbi {
    pub fn from_entrypoint(entrypoint: &str) -> Result<Self, RuntimeV2Error> {
        match entrypoint {
            "score" => Ok(Self::Score),
            "invoke" => Ok(Self::Invoke),
            _ => Err(failure("unsupported WASM entrypoint")),
        }
    }

    fn export_name(self) -> &'static str {
        match self {
            Self::Score => "score",
            Self::Invoke => "invoke",
        }
    }
}

pub(super) struct WasmHost {
    pub(super) abi: ToolAbi,
    engine: Engine,
    module: Module,
    limits: Limits,
    busy: AtomicBool,
}
impl WasmHost {
    pub fn output_limit(&self) -> u64 {
        self.limits.output_bytes
    }
    pub fn compile(bytes: &[u8], limits: Limits, abi: ToolAbi) -> Result<Self, RuntimeV2Error> {
        if bytes.len() > 4 * 1024 * 1024 || !bytes.starts_with(b"\0asm") {
            return Err(failure("invalid WASM binary"));
        }
        let mut config = Config::new();
        // Match adapters-wasmtime: Wasmtime 46's Mach receiver aborts on a caught
        // SIGCHLD (MACH_RCV_INTERRUPTED). Unix handling preserves guest traps.
        // Upstream fix: https://github.com/bytecodealliance/wasmtime/pull/14414
        #[cfg(target_os = "macos")]
        config.macos_use_mach_ports(false);
        config.consume_fuel(true).epoch_interruption(true);
        let engine = Engine::new(&config).map_err(|error| failure(error.to_string()))?;
        let module = Module::new(&engine, bytes).map_err(|error| failure(error.to_string()))?;
        if module.imports().next().is_some() {
            return Err(failure("WASM imports are forbidden"));
        }
        let valid_export = |name| match module.get_export(name) {
            Some(ExternType::Func(ty)) => {
                matches!(ty.params().collect::<Vec<_>>().as_slice(), [ValType::I32])
                    && matches!(ty.results().collect::<Vec<_>>().as_slice(), [ValType::I32])
            }
            _ => false,
        };
        let score = valid_export("score");
        let invoke = valid_export("invoke")
            && matches!(module.get_export("memory"), Some(ExternType::Memory(_)));
        if !matches!(
            (abi, score, invoke),
            (ToolAbi::Score, true, false) | (ToolAbi::Invoke, false, true)
        ) {
            return Err(failure("module must implement only the signed WASM ABI"));
        }
        let host = Self {
            abi,
            engine,
            module,
            limits,
            busy: AtomicBool::new(false),
        };
        host.with_instance(|_, _| Ok(()))?;
        Ok(host)
    }
    pub fn interrupt(&self) {
        self.engine.increment_epoch();
    }
    pub async fn invoke(self: &Arc<Self>, input: Vec<u8>) -> Result<Value, RuntimeV2Error> {
        if self
            .busy
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(failure("WASM concurrency quota exceeded"));
        }
        struct Busy(Arc<WasmHost>);
        impl Drop for Busy {
            fn drop(&mut self) {
                self.0.busy.store(false, Ordering::Release);
            }
        }
        let guard = Busy(Arc::clone(self));
        blocking(move || {
            let result = guard.0.run(&input);
            drop(guard);
            result
        })
        .await
    }
    fn with_instance<T>(
        &self,
        consume: impl FnOnce(&mut Store<StoreLimits>, wasmtime::Instance) -> Result<T, RuntimeV2Error>,
    ) -> Result<T, RuntimeV2Error> {
        let limits = StoreLimitsBuilder::new()
            .memory_size(self.limits.memory)
            .instances(1)
            .tables(1)
            .memories(1)
            .table_elements(1024)
            .trap_on_grow_failure(true)
            .build();
        let mut store: Store<StoreLimits> = Store::new(&self.engine, limits);
        store.limiter(|limits| limits);
        store
            .set_fuel(self.limits.fuel)
            .map_err(|error| failure(error.to_string()))?;
        store.set_epoch_deadline(1);
        let engine = self.engine.clone();
        let wall_ms = self.limits.wall_ms;
        let (stop, stopped) = mpsc::channel();
        let timer = std::thread::Builder::new()
            .name("plugin-wasm-deadline".into())
            .spawn(move || {
                if matches!(
                    stopped.recv_timeout(Duration::from_millis(wall_ms)),
                    Err(mpsc::RecvTimeoutError::Timeout)
                ) {
                    engine.increment_epoch();
                }
            })
            .map_err(|_| failure("WASM deadline worker unavailable"))?;
        let result = (|| {
            let instance = wasmtime::Instance::new(&mut store, &self.module, &[])
                .map_err(|error| failure(error.to_string()))?;
            consume(&mut store, instance)
        })();
        let _ = stop.send(());
        let _ = timer.join();
        result
    }
    fn run(&self, input: &[u8]) -> Result<Value, RuntimeV2Error> {
        self.with_instance(|store, instance| {
            let invoke = instance
                .get_typed_func::<i32, i32>(&mut *store, self.abi.export_name())
                .map_err(|error| failure(error.to_string()))?;
            let input_bytes =
                i32::try_from(input.len()).map_err(|_| failure("WASM input size overflow"))?;
            if self.abi == ToolAbi::Score {
                let score = invoke
                    .call(&mut *store, input_bytes)
                    .map_err(|error| failure(error.to_string()))?;
                return Ok(json!({"score":score, "input_bytes":input_bytes}));
            }
            const OUTPUT_OFFSET: usize = 65536;
            if input.len() > OUTPUT_OFFSET {
                return Err(failure("WASM input exceeds the byte budget"));
            }
            let memory = instance
                .get_memory(&mut *store, "memory")
                .ok_or_else(|| failure("WASM memory unavailable"))?;
            memory
                .write(&mut *store, 0, input)
                .map_err(|_| failure("input exceeds guest memory"))?;
            let length = invoke
                .call(&mut *store, input_bytes)
                .map_err(|error| failure(error.to_string()))?;
            let length =
                usize::try_from(length).map_err(|_| failure("invalid WASM output length"))?;
            if length == 0 || length as u64 > self.limits.output_bytes {
                return Err(failure("WASM output quota exceeded"));
            }
            let bytes = memory
                .data(&*store)
                .get(OUTPUT_OFFSET..OUTPUT_OFFSET + length)
                .ok_or_else(|| failure("WASM output exceeds guest memory"))?;
            let result: Value =
                serde_json::from_slice(bytes).map_err(|_| failure("invalid WASM JSON result"))?;
            if !result.is_object() {
                return Err(failure("WASM output requires a JSON object"));
            }
            Ok(result)
        })
    }
}
