ALTER TABLE password_resets ADD COLUMN IF NOT EXISTS created_at TEXT;
ALTER TABLE password_resets ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
UPDATE password_resets SET used = TRUE WHERE used = FALSE;
UPDATE password_resets SET created_at = CURRENT_TIMESTAMP::text WHERE created_at IS NULL;
ALTER TABLE password_resets ALTER COLUMN created_at SET NOT NULL;