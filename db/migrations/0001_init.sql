-- Full schema for the "scraper" database.
-- Run as app_collector (DB owner) so the default grants for app_bot apply to new tables.

CREATE TABLE groups (
    id               BIGSERIAL PRIMARY KEY,
    tg_chat_id       BIGINT UNIQUE,
    title            TEXT NOT NULL,
    invite_input     TEXT NOT NULL,
    username         TEXT,
    -- 'channel' only for a broadcast channel scraped for links (it has no members); anything with
    -- members is a 'group'. Set at link-scrape time from the resolved entity. See NOTES.md.
    kind             TEXT NOT NULL DEFAULT 'group' CHECK (kind IN ('group', 'channel')),
    is_public        BOOLEAN NOT NULL DEFAULT true,
    first_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_groups_username ON groups (lower(username));

CREATE TABLE members (
    id            BIGSERIAL PRIMARY KEY,
    tg_user_id    BIGINT NOT NULL UNIQUE,
    username      TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_members_username ON members (lower(username));

CREATE TYPE membership_source AS ENUM ('participants', 'messages');

CREATE TABLE group_members (
    id            BIGSERIAL PRIMARY KEY,
    group_id      BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    member_id     BIGINT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    source        membership_source NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_id, member_id, source)
);
CREATE INDEX idx_group_members_member ON group_members (member_id);
CREATE INDEX idx_group_members_group ON group_members (group_id);

CREATE TABLE extracted_links (
    id              BIGSERIAL PRIMARY KEY,
    group_id        BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    link            TEXT NOT NULL,
    link_key        TEXT NOT NULL,
    sender_user_id  BIGINT,
    sender_username TEXT,
    message_date    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_id, link_key)
);
CREATE INDEX idx_links_group ON extracted_links (group_id);

-- The database holds ONLY CSV-derived data (groups, members, group_members, extracted_links). There
-- is no audit/log table: bot activity is recorded in the local file log (log/), not the DB. So a
-- "delete all" (which clears the CSVs -> the watcher prunes these tables) leaves the DB empty.
