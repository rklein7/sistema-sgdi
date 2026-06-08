CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGSERIAL PRIMARY KEY,
  event_type TEXT NOT NULL,
  actor_user_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
  actor_type TEXT NOT NULL DEFAULT 'system',
  entity_type TEXT,
  entity_id TEXT,
  route TEXT,
  method TEXT,
  ip_address INET,
  user_agent TEXT,
  status_code INT,
  request_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
  ON audit_logs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_user_id
  ON audit_logs(actor_user_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type
  ON audit_logs(event_type);

CREATE INDEX IF NOT EXISTS idx_audit_logs_route_method
  ON audit_logs(route, method);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity
  ON audit_logs(entity_type, entity_id);
