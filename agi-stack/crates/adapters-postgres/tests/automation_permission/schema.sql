-- Schema generated from the Alembic-owned SQLAlchemy permission models.

CREATE TABLE agistack_automation_permission_intents (
	id VARCHAR NOT NULL,
	request_id VARCHAR NOT NULL,
	tenant_id VARCHAR NOT NULL,
	project_id VARCHAR NOT NULL,
	job_id VARCHAR NOT NULL,
	run_id VARCHAR NOT NULL,
	conversation_id VARCHAR NOT NULL,
	actor_user_id VARCHAR NOT NULL,
	actor_api_key_id VARCHAR,
	runtime_revision BIGINT NOT NULL,
	invocation_id VARCHAR NOT NULL,
	tool_name VARCHAR NOT NULL,
	tool_version VARCHAR NOT NULL,
	input_sha256 VARCHAR(64) NOT NULL,
	decision_context JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_automation_permission_revision CHECK (runtime_revision > 0),
	CONSTRAINT ck_automation_permission_expiry CHECK (expires_at > created_at),
	UNIQUE (request_id),
	UNIQUE (invocation_id)
)

;

CREATE TABLE agistack_automation_permission_receipts (
	intent_id VARCHAR NOT NULL,
	responder_user_id VARCHAR NOT NULL,
	idempotency_key VARCHAR(255) NOT NULL,
	answer VARCHAR(20) NOT NULL,
	authority_revision BIGINT NOT NULL,
	accepted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (intent_id),
	CONSTRAINT uq_permission_answer_key UNIQUE (responder_user_id, idempotency_key),
	CONSTRAINT ck_permission_answer CHECK (answer IN ('allow_once', 'deny')),
	CONSTRAINT ck_permission_answer_revision CHECK (authority_revision > 0),
	FOREIGN KEY(intent_id) REFERENCES agistack_automation_permission_intents (id)
)

;

CREATE TABLE agistack_automation_permission_consumptions (
	intent_id VARCHAR NOT NULL,
	invocation_id VARCHAR NOT NULL,
	status VARCHAR(30) NOT NULL,
	max_uses BIGINT NOT NULL,
	use_count BIGINT NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (intent_id),
	CONSTRAINT ck_permission_one_use CHECK (max_uses = 1 AND use_count BETWEEN 0 AND 1),
	CONSTRAINT ck_permission_consumption_status CHECK (status IN ('awaiting_dispatch_binding', 'reserved', 'dispatched', 'completed', 'outcome_unknown', 'revoked')),
	FOREIGN KEY(intent_id) REFERENCES agistack_automation_permission_receipts (intent_id),
	UNIQUE (invocation_id)
)

;
