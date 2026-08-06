-- migrations/048_agency_invite_token.sql
-- Anyone who opened the bot became a manager. auth_platform created a Manager row
-- for any valid Telegram initData and attached it to PLATFORM_OWNER_AGENCY_ID --
-- no check that the person had been invited. A stranger who found the bot got a
-- working cabinet with the agency's signals, leads and their clients' personal
-- data: the very data the 152-ФЗ encryption elsewhere exists to protect.
--
-- The token is the invitation. It is unguessable, it belongs to one agency, and
-- the owner can rotate it, which invalidates every link handed out before.

ALTER TABLE agencies ADD COLUMN IF NOT EXISTS invite_token TEXT;

-- Existing agencies get one immediately: without a token nobody could be invited
-- at all, and the pilot agency already has managers to add.
UPDATE agencies SET invite_token = encode(gen_random_bytes(16), 'hex')
WHERE invite_token IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agencies_invite_token
    ON agencies(invite_token) WHERE invite_token IS NOT NULL;
