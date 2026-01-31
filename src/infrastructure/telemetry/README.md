# OpenTelemetry 集成指南

## 概述

MemStack 后端已集成 OpenTelemetry，支持分布式追踪、指标收集和日志关联。

## 环境变量配置

```bash
# 基础配置
SERVICE_NAME=memstack                    # 服务名称
ENVIRONMENT=development                  # 环境: development, staging, production
ENABLE_TELEMETRY=true                    # 启用 OpenTelemetry

# OTLP 导出器配置
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317  # OTLP gRPC 端点
# 或使用 HTTP: http://localhost:4318/v1/traces

# 采样配置
OTEL_TRACES_SAMPLER=traceidratio         # 采样策略
OTEL_TRACES_SAMPLER_ARG=1.0              # 采样率 (1.0 = 100%, 0.1 = 10%)
```

## 本地开发

### 启动 OTel Collector (Docker)

```bash
docker run -d \
  --name otel-collector \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 16686:16686 \
  -p 9411:9411 \
  otel/opentelemetry-collector:latest \
  --config=/etc/otelcol-contrib/config.yaml
```

### 查看追踪

- **Jaeger UI**: http://localhost:16686
- **Zipkin UI**: http://localhost:9411

## 代码使用

### 使用装饰器添加追踪

```python
from src.infrastructure.telemetry import with_tracer, async_with_tracer

@with_tracer("my-component")
def my_function(arg1, arg2):
    return arg1 + arg2

@async_with_tracer("my-component")
async def my_async_function(arg1):
    return await some_operation(arg1)
```

### 手动创建 Span

```python
from src.infrastructure.telemetry import get_tracer

tracer = get_tracer("my-component")
with tracer.start_as_current_span("operation-name") as span:
    span.set_attribute("key", "value")
    span.add_event("event-name", {"attr": "value"})
    # 执行操作
```

### 添加 Span 属性和事件

```python
from src.infrastructure.telemetry import add_span_attributes, add_span_event, set_span_error

# 添加属性
add_span_attributes({"user.id": "123", "action": "create"})

# 添加事件
add_span_event("cache-miss", {"key": "user:123"})

# 记录错误
try:
    operation()
except Exception as e:
    set_span_error(e)
    raise
```

### 获取当前 Trace ID

```python
from src.infrastructure.telemetry import get_trace_id

trace_id = get_trace_id()
if trace_id:
    logger.info(f"Trace ID: {trace_id}")
```

### 指标收集

```python
from src.infrastructure.telemetry import (
    increment_counter,
    record_histogram_value,
    set_gauge,
)

# 计数器
increment_counter("http.requests", "HTTP requests", attributes={"status": "200"})

# 直方图 (记录延迟)
record_histogram_value("http.duration", "Request duration", 123.45)

# 仪表
set_gauge("active.connections", "Active connections", 42)
```

## 生产环境建议

1. **采样率**: 生产环境建议使用 10% 采样率 (`OTEL_TRACES_SAMPLER_ARG=0.1`)
2. **批处理**: 使用 BatchSpanProcessor 提高性能
3. **导出端点**: 使用专用的 OTel Collector 而不是直接导出到后端
4. **认证**: 使用 `OTEL_EXPORTER_OTLP_HEADERS` 设置认证头

## 模块结构

```
src/infrastructure/telemetry/
├── __init__.py       # 公开 API
├── config.py         # OTel 配置和初始化
├── tracing.py        # Tracing 工具函数
├── metrics.py        # Metrics 工具函数
└── decorators.py     # 追踪装饰器
```

## 默认行为

- **开发环境**: 100% 采样，输出到控制台
- **生产环境**: 10% 采样，输出到 OTLP endpoint
- **禁用**: 设置 `ENABLE_TELEMETRY=false`
