-- Challenge живёт между выдачей опций и проверкой ответа браузера.
-- В памяти держать нельзя: процесс на Railway перезапускается в любой момент.
CREATE TABLE webauthn_challenges (
    id         TEXT PRIMARY KEY,
    challenge  BYTEA NOT NULL,
    purpose    TEXT NOT NULL CHECK (purpose IN ('register', 'login')),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ
);
CREATE INDEX webauthn_challenges_cleanup_idx ON webauthn_challenges (expires_at);
