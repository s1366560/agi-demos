use crate::backend::{NativeError, Result};
use gstreamer::{self as gst, prelude::*};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
use tokio::sync::Mutex;

fn device_missing() -> NativeError {
    NativeError::new(
        "audio_unavailable",
        "the requested native audio source is unavailable",
    )
}

struct StartGuard(Option<gst::Pipeline>);
impl Drop for StartGuard {
    fn drop(&mut self) {
        if let Some(pipeline) = self.0.take() {
            let _ = pipeline.set_state(gst::State::Null);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn synthetic_mixed_pipeline_exports_one_playable_pcm_wave() {
        gst::init().unwrap();
        let root = tempfile::tempdir().unwrap();
        let file = root.path().join("synthetic-mixed.wav");
        let input = "audiotestsrc num-buffers=20 samplesperbuffer=480 freq=300 volume=0.25 ! audio/x-raw,format=F32LE,rate=48000,channels=2 ! queue ! mix.";
        let pipeline = gst::parse::launch(&format!("audiomixer name=mix ! audioconvert dithering=none ! audio/x-raw,format=S16LE,rate=48000,channels=2 ! wavenc ! filesink location=\"{}\" {input} {input}",file.display())).unwrap().downcast::<gst::Pipeline>().unwrap();
        let _guard = StartGuard(Some(pipeline.clone()));
        pipeline.set_state(gst::State::Playing).unwrap();
        let message = pipeline
            .bus()
            .unwrap()
            .timed_pop_filtered(
                gst::ClockTime::from_seconds(10),
                &[gst::MessageType::Eos, gst::MessageType::Error],
            )
            .unwrap();
        assert!(
            matches!(message.view(), gst::MessageView::Eos(_)),
            "{message:?}"
        );
        pipeline.set_state(gst::State::Null).unwrap();
        let bytes = std::fs::read(file).unwrap();
        assert_eq!(&bytes[..4], b"RIFF");
        assert_eq!(&bytes[8..12], b"WAVE");
        let mut offset = 12;
        let mut samples = None;
        while offset + 8 <= bytes.len() {
            let length =
                u32::from_le_bytes(bytes[offset + 4..offset + 8].try_into().unwrap()) as usize;
            let chunk = &bytes[offset + 8..offset + 8 + length];
            match &bytes[offset..offset + 4] {
                b"fmt " => {
                    assert_eq!(u16::from_le_bytes(chunk[..2].try_into().unwrap()), 1);
                    assert_eq!(u16::from_le_bytes(chunk[2..4].try_into().unwrap()), 2);
                    assert_eq!(u32::from_le_bytes(chunk[4..8].try_into().unwrap()), 48000);
                    assert_eq!(u16::from_le_bytes(chunk[14..16].try_into().unwrap()), 16);
                }
                b"data" => samples = Some(chunk),
                _ => {}
            }
            offset += 8 + length + length % 2;
        }
        let samples = samples.unwrap();
        assert_eq!(samples.len(), 9600 * 4);
        let peak = samples
            .chunks_exact(2)
            .map(|sample| i16::from_le_bytes(sample.try_into().unwrap()).unsigned_abs())
            .max()
            .unwrap();
        assert!((15000..17000).contains(&peak), "mixed peak={peak}");
    }
}
struct Recording {
    pipeline: gst::Pipeline,
    path: PathBuf,
    watcher: tokio::task::JoinHandle<()>,
    outcome: Arc<std::sync::Mutex<(String, Option<String>)>>,
    source: String,
}
pub struct Audio {
    recordings: Mutex<BTreeMap<String, Recording>>,
}
impl Audio {
    pub fn new() -> Self {
        Self {
            recordings: Mutex::new(BTreeMap::new()),
        }
    }
    fn devices() -> (Option<String>, Option<String>) {
        let default = |argument: &str| {
            let output = std::process::Command::new("pactl")
                .arg(argument)
                .output()
                .map_err(|_| {
                    NativeError::new("audio_unavailable", "PipeWire Pulse service is unavailable")
                })?;
            if !output.status.success() {
                return Err(NativeError::new(
                    "audio_unavailable",
                    "PipeWire Pulse default device unavailable",
                ));
            }
            let value = String::from_utf8(output.stdout)
                .map_err(|_| NativeError::new("audio_unavailable", "invalid audio device id"))?;
            let value = value.trim();
            if value.is_empty() {
                return Err(NativeError::new(
                    "audio_unavailable",
                    "empty audio device id",
                ));
            }
            Ok(value.to_owned())
        };
        (
            default("get-default-source").ok(),
            default("get-default-sink")
                .ok()
                .map(|sink| format!("{sink}.monitor")),
        )
    }
    pub fn capabilities(&self) -> Value {
        let plugins = gst::init().is_ok()
            && [
                "pulsesrc",
                "audioconvert",
                "audioresample",
                "wavenc",
                "filesink",
            ]
            .iter()
            .all(|plugin| gst::ElementFactory::find(plugin).is_some());
        let (mic, system) = Self::devices();
        let state = |available| {
            if available {
                "available"
            } else {
                "unavailable"
            }
        };
        json!({"audio_microphone":{"state":state(plugins && mic.is_some()),"backend":"pulse_or_pipewire_pulse_gstreamer"},"audio_system":{"state":state(plugins && system.is_some()),"backend":"pulse_or_pipewire_pulse_monitor"},"audio_mixed":{"state":state(plugins && mic.is_some() && system.is_some() && gst::ElementFactory::find("audiomixer").is_some()),"backend":"gstreamer_audiomixer"}})
    }
    pub async fn start(
        &self,
        id: &str,
        source: &str,
        root: &Path,
        cancel: Arc<AtomicBool>,
    ) -> Result<Value> {
        let mut recordings = self.recordings.lock().await;
        if !recordings.is_empty() {
            return Err(NativeError::new(
                "audio_busy",
                "another session owns audio capture",
            ));
        }
        gst::init().map_err(|_| NativeError::new("audio_unavailable", "GStreamer unavailable"))?;
        let (mic, system) = Self::devices();
        let quote = |text: &str| text.replace('\\', "\\\\").replace('"', "\\\"");
        let input = |device: &str| {
            format!(
                "pulsesrc device=\"{}\" ! audioconvert ! audioresample ! audio/x-raw,format=F32LE,rate=48000,channels=2",
                quote(device)
            )
        };
        let path = root.join(format!("{}.wav", uuid::Uuid::new_v4()));
        let output = format!(
            "audioconvert ! audio/x-raw,format=S16LE,rate=48000,channels=2 ! wavenc ! filesink location=\"{}\"",
            quote(&path.to_string_lossy())
        );
        let description = match source {
            "microphone" => format!(
                "{} ! {output}",
                input(mic.as_deref().ok_or_else(device_missing)?)
            ),
            "system" => format!(
                "{} ! {output}",
                input(system.as_deref().ok_or_else(device_missing)?)
            ),
            "mixed" => format!(
                "audiomixer name=mix ! {output} {} ! queue ! mix. {} ! queue ! mix.",
                input(mic.as_deref().ok_or_else(device_missing)?),
                input(system.as_deref().ok_or_else(device_missing)?)
            ),
            _ => {
                return Err(NativeError::new(
                    "invalid_params",
                    "source must be microphone, system or mixed",
                ));
            }
        };
        let pipeline = gst::parse::launch(&description)
            .map_err(|_| {
                NativeError::new("audio_unavailable", "cannot create native audio pipeline")
            })?
            .downcast::<gst::Pipeline>()
            .map_err(|_| NativeError::new("audio_unavailable", "invalid audio pipeline"))?;
        let mut guard = StartGuard(Some(pipeline.clone()));
        pipeline.set_state(gst::State::Playing).map_err(|_| {
            NativeError::new("audio_unavailable", "cannot start native audio capture")
        })?;
        let readiness = pipeline.clone();
        let ready = tokio::task::spawn_blocking(move || {
            let (result, state, _) = readiness.state(gst::ClockTime::from_seconds(3));
            result.is_ok() && state == gst::State::Playing
        })
        .await
        .unwrap_or(false);
        if !ready {
            let _ = pipeline.set_state(gst::State::Null);
            return Err(NativeError::new(
                "audio_unavailable",
                "native audio source did not become ready",
            ));
        }
        let observed = pipeline.clone();
        let cancellation = cancel.clone();
        let outcome = Arc::new(std::sync::Mutex::new(("model_stopped".into(), None)));
        let finished = outcome.clone();
        let observed_path = path.clone();
        let watcher = tokio::spawn(async move {
            let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(300);
            loop {
                let failed = observed.bus().is_some_and(|bus| {
                    bus.timed_pop_filtered(gst::ClockTime::ZERO, &[gst::MessageType::Error])
                        .is_some()
                });
                let byte_limit = std::fs::metadata(&observed_path)
                    .is_ok_and(|meta| meta.len() >= 63 * 1024 * 1024);
                if failed
                    || byte_limit
                    || cancellation.load(Ordering::Acquire)
                    || tokio::time::Instant::now() >= deadline
                {
                    if let Ok(mut outcome) = finished.lock() {
                        *outcome = if failed {
                            ("capture_error".into(), Some("audio_capture_failed".into()))
                        } else if byte_limit {
                            ("byte_limit".into(), None)
                        } else if cancellation.load(Ordering::Acquire) {
                            ("cancelled".into(), None)
                        } else {
                            ("duration_limit".into(), None)
                        };
                    }
                    observed.send_event(gst::event::Eos::new());
                    let _ = tokio::task::spawn_blocking(move || {
                        if let Some(bus) = observed.bus() {
                            let _ = bus.timed_pop_filtered(
                                gst::ClockTime::from_seconds(2),
                                &[gst::MessageType::Eos, gst::MessageType::Error],
                            );
                        }
                        let _ = observed.set_state(gst::State::Null);
                    })
                    .await;
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }
        });
        guard.0.take();
        recordings.insert(
            id.into(),
            Recording {
                pipeline,
                path,
                watcher,
                outcome,
                source: source.into(),
            },
        );
        Ok(
            json!({"state":"recording","recording":true,"source":source,"session_id":id,"max_duration_seconds":300}),
        )
    }
    pub async fn stop(&self, id: &str) -> Result<Value> {
        let Some(recording) = self.recordings.lock().await.remove(id) else {
            return Ok(json!({"state":"idle"}));
        };
        recording.watcher.abort();
        recording.pipeline.send_event(gst::event::Eos::new());
        let pipeline = recording.pipeline;
        tokio::task::spawn_blocking(move || {
            if let Some(bus) = pipeline.bus() {
                let _ = bus.timed_pop_filtered(
                    gst::ClockTime::from_seconds(2),
                    &[gst::MessageType::Eos, gst::MessageType::Error],
                );
            }
            let _ = pipeline.set_state(gst::State::Null);
        })
        .await
        .map_err(|_| NativeError::new("audio_failed", "capture worker failed"))?;
        let size = std::fs::metadata(&recording.path)
            .map_err(|_| NativeError::new("audio_failed", "recording artifact unavailable"))?
            .len();
        if size <= 44 {
            return Err(NativeError::new(
                "audio_failed",
                "recording contains no audio samples",
            ));
        }
        let (reason, error) = recording
            .outcome
            .lock()
            .map(|outcome| outcome.clone())
            .unwrap_or_else(|_| ("capture_error".into(), Some("audio_state_failed".into())));
        let artifact = json!({"kind":"audio","source":recording.source,"url":url::Url::from_file_path(recording.path).map_err(|_|NativeError::new("artifact_unavailable","invalid recording URL"))?.as_str(),"mime_type":"audio/wav","size_bytes":size});
        Ok(
            json!({"state":"stopped","recording":false,"artifacts":[artifact],"end_reason":reason,"error_code":error}),
        )
    }
    pub async fn status(&self, id: &str) -> Value {
        let recordings = self.recordings.lock().await;
        let state = match recordings.get(id) {
            Some(recording) if !recording.watcher.is_finished() => "recording",
            Some(_) => "stopped_pending_export",
            None => "idle",
        };
        let (reason, error) = recordings
            .get(id)
            .and_then(|recording| recording.outcome.lock().ok().map(|outcome| outcome.clone()))
            .unwrap_or_default();
        json!({"state":state,"recording":state=="recording","end_reason":reason,"error_code":error})
    }
}
