CREATE TABLE users (
    vk_id       BIGINT PRIMARY KEY,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    photo_url   TEXT NOT NULL DEFAULT '',
    can_write   BOOLEAN NOT NULL DEFAULT TRUE,
    state       TEXT NOT NULL DEFAULT 'idle',
    state_data  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tickets (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(vk_id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'closed')),
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_reply_at  TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    unread_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX tickets_queue_idx ON tickets (status, last_message_at DESC);
-- У пользователя не может быть двух незакрытых обращений одновременно.
CREATE UNIQUE INDEX tickets_one_open_per_user
    ON tickets (user_id) WHERE status <> 'closed';

CREATE TABLE ticket_messages (
    id             BIGSERIAL PRIMARY KEY,
    ticket_id      BIGINT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    direction      TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    text           TEXT NOT NULL DEFAULT '',
    attachments    JSONB NOT NULL DEFAULT '[]'::jsonb,
    vk_message_id  BIGINT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at        TIMESTAMPTZ
);
CREATE INDEX ticket_messages_feed_idx ON ticket_messages (ticket_id, created_at);

CREATE TABLE faq (
    id        BIGSERIAL PRIMARY KEY,
    title     TEXT NOT NULL,
    answer    TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX faq_order_idx ON faq (is_active, position);

CREATE TABLE processed_events (
    event_id   TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX processed_events_cleanup_idx ON processed_events (created_at);

CREATE TABLE outbox (
    id              BIGSERIAL PRIMARY KEY,
    peer_id         BIGINT NOT NULL,
    payload         JSONB NOT NULL,
    random_id       INTEGER NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);
CREATE INDEX outbox_worker_idx ON outbox (status, next_attempt_at) WHERE status = 'pending';

CREATE TABLE admin_credentials (
    id            BIGSERIAL PRIMARY KEY,
    credential_id BYTEA NOT NULL UNIQUE,
    public_key    BYTEA NOT NULL,
    sign_count    BIGINT NOT NULL DEFAULT 0,
    transports    TEXT[] NOT NULL DEFAULT '{}',
    name          TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ
);

CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX sessions_expiry_idx ON sessions (expires_at);

CREATE TABLE push_subscriptions (
    id         BIGSERIAL PRIMARY KEY,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_ok_at TIMESTAMPTZ
);

CREATE TABLE setup_tokens (
    token_hash TEXT PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ
);
