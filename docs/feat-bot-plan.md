# feat/bot Branch - Implement Clawdbot-like Features

## Goal
Implement core Clawdbot-like features in MemStack, focusing on:
- Session management
- Heartbeat system
- Multi-channel messaging
- Skill system
- Tool orchestration

## Current State Analysis

### What MemStack Already Has
✅ Multi-level agent thinking (Work/Task level)
✅ Human-AI collaboration
✅ Knowledge & memory management
✅ Multi-tenant architecture
✅ LLM provider support
✅ Web chat UI
✅ Tool layer (basic tools, MCP)
✅ Skill layer (document-based)

### What Clawdbot Has That MemStack Needs
❌ Session management (spawn, list, send, history)
❌ Heartbeat system with periodic checks
❌ Multi-channel messaging (Telegram, WhatsApp, Discord, Signal, iMessage)
❌ Session isolation and memory per session
❌ Cron/reminder system
❌ Browser control with session management
❌ Node control (canvases, paired devices)
❌ Reply tagging system
❌ SOUL.md/USER.md/IDENTITY.md personality system

## Implementation Plan

### Phase 1: Core Session Management (Priority: HIGH)

#### 1.1 Session Model & Repository
- **Domain Layer**: Create `Session` entity with:
  - `session_key` (unique identifier)
  - `agent_id` (which agent handles this session)
  - `model` (model override for this session)
  - `status` (active/inactive/terminated)
  - `created_at`, `last_active_at`
  - `metadata` (flexible JSON for channel, user, etc.)

- **Infrastructure**: Create `SessionRepository` in PostgreSQL
- **API**: CRUD endpoints for session management

#### 1.2 Session Operations
- `spawn`: Create new sub-agent session
- `list`: List sessions with filters (active, kind, limit)
- `send`: Send message to another session
- `history`: Fetch message history for a session
- `terminate`: Close a session

#### 1.3 Session Memory Isolation
- Each session has its own memory context
- Cross-session communication via `sessions_send`
- Session-scoped environment variables

### Phase 2: Heartbeat System (Priority: HIGH)

#### 2.1 Heartbeat Infrastructure
- **Heartbeat Trigger**: Configurable message pattern
- **HEARTBEAT.md**: File for heartbeat tasks
- **State Tracking**: `heartbeat-state.json` for tracking last checks

#### 2.2 Built-in Heartbeat Tasks
- Email checks
- Calendar events
- Weather
- Notifications
- Memory maintenance

#### 2.3 Smart Heartbeat Logic
- Batch checks (don't spam)
- Time-aware (quiet hours)
- Proactive alerts only when needed
- Reply with `HEARTBEAT_OK` when idle

### Phase 3: Multi-Channel Messaging (Priority: MEDIUM)

#### 3.1 Channel Architecture
- **Abstract Channel Interface**: Base class for all channels
- **Channel Manager**: Route messages to appropriate channel
- **Channel Registry**: Dynamic channel loading

#### 3.2 Channel Implementations
- **WebChat**: Already exists, adapt for session model
- **Telegram**: Bot API integration
- **WhatsApp**: Business API
- **Discord**: Bot integration
- **Signal**: (if feasible)
- **iMessage**: (macOS only, requires permissions)

#### 3.3 Message Features
- Reply tagging (`[[reply_to_current]]`, `[[reply_to:<id>]]`)
- Reactions (emoji support)
- Inline buttons (where supported)
- Media attachments

### Phase 4: Skill System Enhancement (Priority: MEDIUM)

#### 4.1 Skill Structure
- **SKILL.md**: Standardized skill format
- **Skill Metadata**: Name, description, tags
- **Skill Loading**: Auto-discovery from skills/ directory

#### 4.2 Built-in Skills
- `coding-agent`: Run coding agents
- `github`: GitHub CLI integration
- `tmux`: Remote tmux control
- `weather`: Weather queries
- `notion`: Notion API
- `slack`: Slack control

#### 4.3 Skill Activation
- Trigger-based activation
- Manual invocation
- Context-aware suggestions

### Phase 5: Cron/Reminder System (Priority: MEDIUM)

#### 5.1 Cron Infrastructure
- **Cron Job Model**: Schedule, task text, target channel
- **Cron Executor**: Background scheduler
- **Job Management**: Add, update, remove, run, list runs

#### 5.2 Reminder Features
- One-shot reminders
- Recurring schedules
- Wake events
- System event triggers

### Phase 6: Advanced Control (Priority: LOW)

#### 6.1 Browser Control
- Browser session management
- Chrome extension relay
- Snapshot & actions

#### 6.2 Node Control
- Paired device management
- Camera snapshots
- Screen recording
- Location tracking

#### 6.3 Canvas Control
- Canvas presentation
- A2UI integration

## Technical Architecture

### Domain Layer Extensions
```
src/domain/model/
├── session/
│   ├── entities.py           # Session, SessionMessage
│   ├── value_objects.py      # SessionKey, SessionStatus
│   └── aggregates.py         # SessionAggregate
├── channel/
│   ├── entities.py           # Channel, Message
│   └── enums.py              # ChannelType, MessageType
├── heartbeat/
│   ├── entities.py           # HeartbeatTask, HeartbeatState
│   └── value_objects.py      # HeartbeatSchedule
└── cron/
    ├── entities.py           # CronJob, CronExecution
    └── value_objects.py      # CronSchedule
```

### Application Layer Extensions
```
src/application/use_cases/
├── session/
│   ├── spawn_session.py
│   ├── list_sessions.py
│   ├── send_to_session.py
│   ├── get_session_history.py
│   └── terminate_session.py
├── heartbeat/
│   ├── execute_heartbeat.py
│   ├── update_heartbeat_state.py
│   └── get_heartbeat_status.py
├── channel/
│   ├── send_message.py
│   ├── handle_incoming.py
│   └── register_channel.py
└── cron/
    ├── schedule_cron_job.py
    ├── execute_cron_job.py
    └── list_cron_jobs.py
```

### Infrastructure Layer Extensions
```
src/infrastructure/
├── adapters/
│   ├── primary/
│   │   ├── session_api.py    # Session REST API
│   │   ├── channel_api.py    # Channel REST API
│   │   └── cron_api.py       # Cron REST API
│   └── secondary/
│       ├── session_repository.py    # PostgreSQL
│       ├── cron_repository.py      # PostgreSQL
│       └── heartbeat_file_repository.py  # File system
├── channel/
│   ├── base.py               # Abstract Channel
│   ├── webchat.py            # WebChat channel
│   ├── telegram.py           # Telegram channel
│   ├── discord.py            # Discord channel
│   └── whatsapp.py           # WhatsApp channel
├── scheduler/
│   ├── cron_executor.py      # Cron job executor
│   ├── heartbeat_executor.py # Heartbeat executor
│   └── background_worker.py  # Background task worker
└── messaging/
    ├── channel_manager.py    # Channel routing
    └── message_router.py     # Message distribution
```

## Implementation Priority

### Sprint 1: Foundation
1. Session model and repository
2. Session spawn/list API
3. Basic heartbeat infrastructure
4. Session memory isolation

### Sprint 2: Communication
1. Channel abstraction layer
2. WebChat channel adaptation
3. Message routing
4. Reply tagging

### Sprint 3: Automation
1. Cron job model and executor
2. One-shot reminders
3. Heartbeat task execution
4. Proactive alerts

### Sprint 4: Channels
1. Telegram integration
2. Discord integration
3. WhatsApp integration
4. Channel configuration

### Sprint 5: Advanced Features
1. Skill system enhancements
2. Built-in skills
3. Browser control
4. Node control

## Dependencies

### Required
- Existing MemStack infrastructure (✅ already present)
- PostgreSQL for session/cron storage
- Background task queue (Redis + Celery or similar)

### Optional (for specific channels)
- Telegram Bot API token
- Discord Bot token
- WhatsApp Business API credentials
- Signal CLI (if implemented)

## Testing Strategy

### Unit Tests
- Session entity and repository
- Channel abstractions
- Heartbeat logic
- Cron scheduling

### Integration Tests
- Session spawn → send → history flow
- Heartbeat execution with state tracking
- Cron job scheduling and execution
- Message routing across channels

### E2E Tests
- Full user flow: spawn session → send messages → receive responses
- Heartbeat cycle with proactive alerts
- Cron reminder lifecycle

## Migration Plan

### Database Migrations
```sql
-- Sessions table
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_key VARCHAR(255) UNIQUE NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    model VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_active_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Session messages table
CREATE TABLE session_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Cron jobs table
CREATE TABLE cron_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id VARCHAR(255) UNIQUE NOT NULL,
    schedule VARCHAR(255) NOT NULL,
    task_text TEXT NOT NULL,
    target_channel VARCHAR(255),
    metadata JSONB DEFAULT '{}',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Cron executions table
CREATE TABLE cron_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES cron_jobs(id) ON DELETE CASCADE,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) NOT NULL,
    output TEXT,
    error TEXT
);
```

## Success Metrics

- [ ] Session spawn → send → history flow working
- [ ] Heartbeat system with state tracking
- [ ] At least 2 external channels (Telegram, Discord) working
- [ ] Cron jobs scheduling and executing
- [ ] Test coverage > 80% for new features
- [ ] Documentation complete

## Notes

- This is a phased implementation, prioritize core features first
- Maintain MemStack's DDD architecture throughout
- Leverage existing infrastructure where possible
- Follow MemStack's coding standards (see CLAUDE.md)
- Keep backward compatibility with existing MemStack features
