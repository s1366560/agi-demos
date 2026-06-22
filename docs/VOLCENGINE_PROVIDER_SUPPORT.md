# Volcengine (Doubao) Provider Support

MemStack provides support for Volcengine (火山引擎/豆包 Doubao) services, including LLM, Vision, and Audio.

> Last checked against code: 2026-06-22

## LLM Configuration

Volcengine models are accessed via **Deployment Endpoint IDs** (`ep-xxx`).

### Environment Variables
- `VOLC_AK`: Access Key
- `VOLC_SK`: Secret Key
- `VOLC_APP_ID`: Application ID for Voice services

### Supported Models
| Model Category | Registry ID | Context Window |
|----------------|-------------|----------------|
| **Chat** | `doubao-1.5-pro` | 128k/256k |
| | `doubao-1.5-lite` | 128k/256k |
| **Vision** | `doubao-vision` | 128k |
| **Embedding** | `doubao-embedding-large` | 2560 dim |
| **Reranker** | `doubao-reranker-large` | - |

## Audio Services

MemStack implements specialized adapters for Volcengine Audio APIs which deviate from OpenAI standards.

### ASR (Speech-to-Text)
- **Adapter**: `VolcengineASRAdapter`
- **Pattern**: Submit/Query asynchronous task pattern.
- **Config**: `VOLC_ASR_CLUSTER` (default: `volcano_asr`)

### TTS (Text-to-Speech)
- **Adapter**: `VolcengineTTSAdapter`
- **Pattern**: Doubao Speech Synthesis 2.0 (HTTP Chunked/SSE).
- **Config**: `VOLC_TTS_RESOURCE_ID` (default: `volc.speech.dialog`)

## Instantiation

The ASR and TTS adapters are plain classes and are not wired through `DIContainer`. Construct them directly with Volcengine credentials:

```python
from src.infrastructure.adapters.secondary.external.volcengine.audio_adapters import (
    VolcengineASRAdapter,
    VolcengineTTSAdapter,
)

asr_service = VolcengineASRAdapter(access_key=volc_ak, app_key=volc_app_id)
tts_service = VolcengineTTSAdapter(access_key=volc_ak, app_key=volc_app_id)
```

> Note: A Volcengine RTC ("real-time voice chat") adapter is not implemented. Only ASR and TTS adapters ship in `src/infrastructure/adapters/secondary/external/volcengine/`.
