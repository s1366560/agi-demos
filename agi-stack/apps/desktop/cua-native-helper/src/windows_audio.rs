//! WASAPI shared-mode microphone and render-loopback capture on owned MTA threads.
use crate::{
    backend::{NativeError, Result},
    wave::Wave,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;
use windows::Win32::{
    Media::Audio::{
        AUDCLNT_BUFFERFLAGS_SILENT, AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK,
        IAudioCaptureClient, IAudioClient, IMMDeviceEnumerator, MMDeviceEnumerator, eCapture,
        eConsole, eRender,
    },
    System::Com::{
        CLSCTX_ALL, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx, CoTaskMemFree,
        CoUninitialize,
    },
};

struct Worker {
    stop: Arc<AtomicBool>,
    thread: thread::JoinHandle<Result<Value>>,
}
pub struct Audio {
    workers: Mutex<BTreeMap<String, Vec<Worker>>>,
}
impl Audio {
    pub fn new() -> Self {
        Self {
            workers: Mutex::new(BTreeMap::new()),
        }
    }
    pub fn capabilities(&self) -> Value {
        // Endpoint enumeration does not start recording or request new credentials.
        let available = unsafe {
            CoCreateInstance::<_, IMMDeviceEnumerator>(&MMDeviceEnumerator, None, CLSCTX_ALL)
        };
        let mic = available.as_ref().is_ok_and(|enumerator| unsafe {
            enumerator
                .GetDefaultAudioEndpoint(eCapture, eConsole)
                .is_ok()
        });
        let system = available.as_ref().is_ok_and(|enumerator| unsafe {
            enumerator
                .GetDefaultAudioEndpoint(eRender, eConsole)
                .is_ok()
        });
        let state = |ready| if ready { "available" } else { "unavailable" };
        json!({"audio_microphone":{"state":state(mic),"backend":"wasapi"},"audio_system":{"state":state(system),"backend":"wasapi_loopback"},"audio_mixed":{"state":state(mic&&system),"format":"wav","backend":"wasapi"}})
    }
    pub async fn start(
        &self,
        id: &str,
        source: &str,
        root: &Path,
        cancel: Arc<AtomicBool>,
    ) -> Result<Value> {
        let mut workers = self.workers.lock().await;
        if !workers.is_empty() {
            return Err(NativeError::new(
                "audio_busy",
                "another session owns audio capture",
            ));
        }
        let sources = match source {
            "microphone" => vec![false],
            "system" => vec![true],
            "mixed" => vec![false, true],
            _ => {
                return Err(NativeError::new(
                    "invalid_params",
                    "source must be microphone, system or mixed",
                ));
            }
        };
        let origin = clock_100ns()?;
        workers.insert(id.into(), Vec::new());
        let group_stop = Arc::new(AtomicBool::new(false));
        for system in sources {
            let path = root.join(format!("{}.wav", uuid::Uuid::new_v4()));
            let stop = group_stop.clone();
            let flag = stop.clone();
            let cancellation = cancel.clone();
            let (ready, sent) = std::sync::mpsc::sync_channel(1);
            let worker =
                thread::spawn(move || capture(system, path, flag, cancellation, ready, origin));
            workers
                .get_mut(id)
                .expect("owned audio entry exists")
                .push(Worker {
                    stop: stop.clone(),
                    thread: worker,
                });
            let result =
                tokio::task::spawn_blocking(move || sent.recv_timeout(Duration::from_secs(5)))
                    .await;
            if !matches!(result, Ok(Ok(Ok(())))) {
                stop.store(true, Ordering::Release);
                let active = workers.get(id).expect("owned audio entry exists");
                for worker in active {
                    worker.stop.store(true, Ordering::Release);
                }
                // The receipt manager calls stop even after start failure, retaining
                // any samples already captured by the other mixed source.
                return Err(NativeError::new(
                    "audio_unavailable",
                    "WASAPI initialization or microphone permission failed",
                ));
            }
        }
        Ok(json!({"recording":true,"source":source,"format":"wav","max_duration_seconds":300}))
    }
    pub async fn stop(&self, id: &str) -> Result<Value> {
        let Some(workers) = self.workers.lock().await.remove(id) else {
            return Ok(json!({"recording":false}));
        };
        for worker in &workers {
            worker.stop.store(true, Ordering::Release);
        }
        let mut artifacts = Vec::new();
        let mut error_code = None;
        let mut end_reason = None;
        for worker in workers {
            let result = tokio::task::spawn_blocking(move || worker.thread.join())
                .await
                .map_err(|_| NativeError::new("audio_failed", "capture worker failed"))
                .and_then(|joined| {
                    joined.map_err(|_| NativeError::new("audio_failed", "capture thread panicked"))
                })
                .and_then(|captured| captured);
            match result {
                Ok(artifact) => {
                    error_code =
                        error_code.or_else(|| artifact["error_code"].as_str().map(str::to_owned));
                    if end_reason
                        .as_deref()
                        .is_none_or(|reason| reason == "model_stopped")
                    {
                        end_reason = artifact["end_reason"].as_str().map(str::to_owned);
                    }
                    artifacts.push(artifact);
                }
                Err(error) => {
                    error_code = error_code.or(Some(error.kind));
                }
            }
        }
        if artifacts.len() == 2 && error_code.is_none() {
            let decode = |artifact: &Value| {
                url::Url::parse(
                    artifact["url"]
                        .as_str()
                        .ok_or_else(|| NativeError::new("audio_failed", "recording URL missing"))?,
                )
                .ok()
                .and_then(|url| url.to_file_path().ok())
                .ok_or_else(|| NativeError::new("audio_failed", "invalid native recording URL"))
            };
            let first = decode(&artifacts[0])?;
            let second = decode(&artifacts[1])?;
            let offset_a = artifacts[0]["start_offset_seconds"].as_f64().unwrap_or(0.0);
            let offset_b = artifacts[1]["start_offset_seconds"].as_f64().unwrap_or(0.0);
            let mixed = first
                .parent()
                .ok_or_else(|| {
                    NativeError::new("artifact_unavailable", "native recording directory missing")
                })?
                .join(format!("{}.wav", uuid::Uuid::new_v4()));
            let output = mixed.clone();
            let mixed_result = tokio::task::spawn_blocking(move || {
                crate::audio_mix::mix(&first, offset_a, &second, offset_b, &output)
            })
            .await
            .map_err(|_| NativeError::new("audio_failed", "native mixing worker failed"))
            .and_then(|result| result);
            let bytes = match mixed_result {
                Ok(bytes) => bytes,
                Err(error) => {
                    return Ok(
                        json!({"recording":false,"format":"wav","artifacts":artifacts,"error_code":error.kind,"end_reason":end_reason}),
                    );
                }
            };
            let artifact = json!({"kind":"audio","source":"mixed","url":url::Url::from_file_path(mixed).map_err(|_|NativeError::new("artifact_unavailable","invalid mixed recording URL"))?.as_str(),"mime_type":"audio/wav","data_bytes":bytes,"sample_rate":48000,"channels":2});
            return Ok(
                json!({"recording":false,"format":"wav","artifacts":[artifact],"source_artifacts":artifacts,"end_reason":end_reason}),
            );
        }
        if error_code.is_some()
            && end_reason
                .as_deref()
                .is_none_or(|reason| reason == "model_stopped")
        {
            end_reason = Some("capture_error".into());
        }
        Ok(
            json!({"recording":false,"artifacts":artifacts,"format":"wav","error_code":error_code,"end_reason":end_reason}),
        )
    }
    pub async fn status(&self, id: &str) -> Value {
        let workers = self.workers.lock().await;
        json!({"recording":workers.get(id).is_some_and(|workers|!workers.is_empty() && workers.iter().all(|worker|!worker.thread.is_finished()))})
    }
}
struct Apartment;
impl Drop for Apartment {
    fn drop(&mut self) {
        unsafe {
            CoUninitialize();
        }
    }
}
fn capture(
    system: bool,
    path: PathBuf,
    stop: Arc<AtomicBool>,
    cancel: Arc<AtomicBool>,
    ready: std::sync::mpsc::SyncSender<Result<()>>,
    origin: u64,
) -> Result<Value> {
    // SAFETY: all COM interfaces and audio packet pointers stay on this owned MTA thread.
    unsafe {
        let init = CoInitializeEx(None, COINIT_MULTITHREADED)
            .ok()
            .map_err(|_| NativeError::new("audio_unavailable", "COM audio apartment unavailable"));
        if let Err(error) = init {
            let _ = ready.send(Err(error.clone()));
            return Err(error);
        }
        let _apartment = Apartment;
        let setup = (|| -> Result<_> {
            let enumerator: IMMDeviceEnumerator =
                CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL).map_err(|_| {
                    NativeError::new("audio_unavailable", "WASAPI device enumeration failed")
                })?;
            let device = enumerator
                .GetDefaultAudioEndpoint(if system { eRender } else { eCapture }, eConsole)
                .map_err(|_| {
                    NativeError::new("audio_unavailable", "default audio endpoint unavailable")
                })?;
            let client: IAudioClient = device.Activate(CLSCTX_ALL, None).map_err(|_| {
                NativeError::new("audio_unavailable", "audio endpoint activation failed")
            })?;
            let format = client.GetMixFormat().map_err(|_| {
                NativeError::new("audio_format_unsupported", "native mix format unavailable")
            })?;
            if format.is_null() {
                return Err(NativeError::new(
                    "audio_format_unsupported",
                    "empty mix format",
                ));
            }
            let format_len = 18 + (*format).cbSize as usize;
            let block = (*format).nBlockAlign as usize;
            if !(18..=80).contains(&format_len) || block == 0 || block > 128 {
                CoTaskMemFree(Some(format.cast()));
                return Err(NativeError::new(
                    "audio_format_unsupported",
                    "invalid sample format",
                ));
            }
            let format_bytes = std::slice::from_raw_parts(format.cast::<u8>(), format_len).to_vec();
            let initialized = client.Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                if system {
                    AUDCLNT_STREAMFLAGS_LOOPBACK
                } else {
                    0
                },
                10_000_000,
                0,
                format,
                None,
            );
            CoTaskMemFree(Some(format.cast()));
            initialized.map_err(|_| {
                NativeError::new("permission_required", "WASAPI rejected shared-mode capture")
            })?;
            let capture: IAudioCaptureClient = client.GetService().map_err(|_| {
                NativeError::new("audio_unavailable", "audio capture service unavailable")
            })?;
            let wave = Wave::create(&path, &format_bytes)?;
            client.Start().map_err(|_| {
                NativeError::new("permission_required", "WASAPI capture could not start")
            })?;
            Ok((client, capture, wave, block))
        })();
        let (client, capture, mut wave, block) = match setup {
            Ok(setup) => {
                let _ = ready.send(Ok(()));
                setup
            }
            Err(error) => {
                let _ = ready.send(Err(error.clone()));
                return Err(error);
            }
        };
        let deadline = Instant::now() + Duration::from_secs(300);
        let mut first_timestamp = None;
        let result = (|| -> Result<()> {
            while !stop.load(Ordering::Acquire)
                && !cancel.load(Ordering::Acquire)
                && Instant::now() < deadline
            {
                while capture
                    .GetNextPacketSize()
                    .map_err(|_| NativeError::new("audio_failed", "WASAPI packet query failed"))?
                    > 0
                {
                    let mut data = std::ptr::null_mut();
                    let mut frames = 0;
                    let mut flags = 0;
                    let mut timestamp = 0;
                    capture
                        .GetBuffer(
                            &mut data,
                            &mut frames,
                            &mut flags,
                            None,
                            Some(&mut timestamp),
                        )
                        .map_err(|_| {
                            NativeError::new("audio_failed", "WASAPI buffer unavailable")
                        })?;
                    if first_timestamp.is_none() {
                        first_timestamp = Some(if timestamp > 0 {
                            timestamp
                        } else {
                            clock_100ns()?
                        });
                    }
                    let count = (frames as usize)
                        .checked_mul(block)
                        .filter(|count| *count <= 16 * 1024 * 1024)
                        .ok_or_else(|| {
                            NativeError::new("audio_limit", "native audio packet exceeds budget")
                        })?;
                    let written = if flags & AUDCLNT_BUFFERFLAGS_SILENT.0 as u32 != 0 {
                        wave.append(&vec![0; count])
                    } else if data.is_null() {
                        Err(NativeError::new(
                            "audio_failed",
                            "empty WASAPI sample pointer",
                        ))
                    } else {
                        wave.append(std::slice::from_raw_parts(data, count))
                    };
                    let release = capture.ReleaseBuffer(frames);
                    written?;
                    release.map_err(|_| {
                        NativeError::new("audio_failed", "WASAPI buffer release failed")
                    })?;
                }
                thread::sleep(Duration::from_millis(10));
            }
            Ok(())
        })();
        let _ = client.Stop();
        let reason = if Instant::now() >= deadline {
            "duration_limit"
        } else if cancel.load(Ordering::Acquire) {
            "cancelled"
        } else if result
            .as_ref()
            .is_err_and(|error| error.kind == "audio_limit")
        {
            "byte_limit"
        } else if result.is_err() {
            "capture_error"
        } else {
            "model_stopped"
        };
        // Ending either mixed source terminates the entire group promptly.
        stop.store(true, Ordering::Release);
        let bytes = wave.finish()?;
        if bytes == 0 {
            return Err(NativeError::new(
                "audio_failed",
                "capture produced no native audio samples",
            ));
        }
        Ok(
            json!({"kind":"audio","source":if system{"system"}else{"microphone"},"url":url::Url::from_file_path(path).map_err(|_|NativeError::new("artifact_unavailable","invalid recording URL"))?.as_str(),"mime_type":"audio/wav","data_bytes":bytes,"end_reason":reason,"error_code":result.err().filter(|error|error.kind!="audio_limit").map(|error|error.kind),"start_offset_seconds":first_timestamp.unwrap_or(origin).saturating_sub(origin) as f64/10_000_000.0}),
        )
    }
}

fn clock_100ns() -> Result<u64> {
    use windows::Win32::System::Performance::{QueryPerformanceCounter, QueryPerformanceFrequency};
    let mut ticks = 0;
    let mut rate = 0;
    unsafe {
        QueryPerformanceCounter(&mut ticks).map_err(|_| {
            NativeError::new(
                "audio_alignment_unavailable",
                "native capture clock unavailable",
            )
        })?;
        QueryPerformanceFrequency(&mut rate).map_err(|_| {
            NativeError::new(
                "audio_alignment_unavailable",
                "native capture clock unavailable",
            )
        })?;
    }
    if ticks < 0 || rate <= 0 {
        return Err(NativeError::new(
            "audio_alignment_unavailable",
            "invalid native capture clock",
        ));
    }
    Ok(((ticks as u128) * 10_000_000 / (rate as u128)) as u64)
}
