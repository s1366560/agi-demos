use super::failure;
use crate::protocol_v2::{QuotaV2, RuntimeV2Error};
use futures::channel::oneshot;
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
        let host = ScoreHost::compile(
            &bytes,
            Limits {
                fuel: u64::MAX,
                memory: 65536,
                wall_ms: 5,
                output_bytes: 1024,
            },
        )
        .unwrap();
        let start = std::time::Instant::now();
        assert!(host.run(1).is_err());
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
        let output_bytes = capped(manifest.max_output_bytes, entry.max_output_bytes, 16_384);
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

pub(super) struct ScoreHost {
    engine: Engine,
    module: Module,
    limits: Limits,
    busy: AtomicBool,
}
impl ScoreHost {
    pub fn output_limit(&self) -> u64 {
        self.limits.output_bytes
    }
    pub fn compile(bytes: &[u8], limits: Limits) -> Result<Self, RuntimeV2Error> {
        if bytes.len() > 4 * 1024 * 1024 || !bytes.starts_with(b"\0asm") {
            return Err(failure("invalid WASM binary"));
        }
        let mut config = Config::new();
        config.consume_fuel(true).epoch_interruption(true);
        let engine = Engine::new(&config).map_err(|error| failure(error.to_string()))?;
        let module = Module::new(&engine, bytes).map_err(|error| failure(error.to_string()))?;
        if module.imports().next().is_some() {
            return Err(failure("WASM imports are forbidden"));
        }
        let Some(ExternType::Func(score)) = module.get_export("score") else {
            return Err(failure("score export required"));
        };
        let params: Vec<_> = score.params().collect();
        let results: Vec<_> = score.results().collect();
        if params.len() != 1
            || results.len() != 1
            || !matches!(params[0], ValType::I32)
            || !matches!(results[0], ValType::I32)
        {
            return Err(failure("score ABI requires i32 -> i32"));
        }
        Ok(Self {
            engine,
            module,
            limits,
            busy: AtomicBool::new(false),
        })
    }
    pub fn interrupt(&self) {
        self.engine.increment_epoch();
    }
    pub async fn invoke(self: &Arc<Self>, input_bytes: i32) -> Result<i32, RuntimeV2Error> {
        if self
            .busy
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(failure("WASM concurrency quota exceeded"));
        }
        struct Busy(Arc<ScoreHost>);
        impl Drop for Busy {
            fn drop(&mut self) {
                self.0.busy.store(false, Ordering::Release);
            }
        }
        let guard = Busy(Arc::clone(self));
        blocking(move || {
            let result = guard.0.run(input_bytes);
            drop(guard);
            result
        })
        .await
    }
    fn run(&self, input_bytes: i32) -> Result<i32, RuntimeV2Error> {
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
            let score = instance
                .get_typed_func::<i32, i32>(&mut store, "score")
                .map_err(|error| failure(error.to_string()))?;
            score
                .call(&mut store, input_bytes)
                .map_err(|error| failure(error.to_string()))
        })();
        let _ = stop.send(());
        let _ = timer.join();
        result
    }
}
