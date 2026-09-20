-- Кто взял обращение в работу. Имя и роль закрепляются за обращением навсегда:
-- клиент уже увидел, кем ему представились, менять это на полпути нельзя.
ALTER TABLE tickets
    ADD COLUMN operator_name TEXT,
    ADD COLUMN operator_role TEXT,
    ADD COLUMN operator_tier TEXT CHECK (operator_tier IN ('operator', 'lead')),
    ADD COLUMN taken_at TIMESTAMPTZ;

CREATE INDEX tickets_taken_idx ON tickets (taken_at) WHERE taken_at IS NOT NULL;
