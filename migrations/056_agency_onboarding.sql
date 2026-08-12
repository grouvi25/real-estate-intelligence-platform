ALTER TABLE agencies ADD COLUMN IF NOT EXISTS onboarding_code TEXT UNIQUE;
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
UPDATE agencies SET onboarding_code = COALESCE(onboarding_code, invite_token, substr(md5(random()::text),1,12)) WHERE onboarding_code IS NULL;
