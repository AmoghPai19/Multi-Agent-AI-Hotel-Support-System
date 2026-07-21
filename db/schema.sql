-- ============================================================================
--  schema.sql  —  Core data model (portable: runs on ANY PostgreSQL 16+)
--  Multi-Agent AI Hotel Support System
--
--  Three logical areas in ONE database:
--    1. Inventory + Reservations (transactional booking data)
--    2. Conversation history + Audit logs
--    3. Policy store for RAG (pgvector)
--
--  Supabase-specific wiring (FK to auth.users, signup trigger, RLS) lives in
--  db/supabase/auth.sql and is applied ONLY against the Supabase project.
-- ============================================================================

-- Extensions --------------------------------------------------------------
-- gen_random_uuid() is core in PG13+, but pgcrypto is kept for parity with prod.
create extension if not exists pgcrypto;
-- pgvector: adds the `vector` type + similarity indexes (for RAG in §3).
create extension if not exists vector;
-- citext: a case-INsensitive text type, so 'Amogh@x.com' == 'amogh@x.com'.
create extension if not exists citext;


-- ============================================================================
-- 1. INVENTORY
-- ============================================================================

-- A hotel property. The design supports one or many; v1 is single-property.
create table properties (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    city        text not null,
    timezone    text not null default 'UTC',
    created_at  timestamptz not null default now()
);

-- A category of room (e.g. Standard, Deluxe, Suite). Price + capacity live here.
create table room_types (
    id              uuid primary key default gen_random_uuid(),
    property_id     uuid not null references properties(id) on delete cascade,
    code            text not null,                       -- 'STD' | 'DLX' | 'SUITE'
    name            text not null,                       -- 'Deluxe King'
    max_occupancy   smallint not null check (max_occupancy > 0),
    base_rate_cents integer  not null check (base_rate_cents >= 0),  -- money as int cents
    currency        char(3)  not null default 'USD',
    unique (property_id, code)                           -- no duplicate codes per hotel
);

-- A physical room belonging to a room type.
create table rooms (
    id            uuid primary key default gen_random_uuid(),
    room_type_id  uuid not null references room_types(id) on delete cascade,
    room_number   text not null,
    floor         smallint,
    is_active     boolean not null default true,
    unique (room_type_id, room_number)
);


-- ============================================================================
-- 2. GUESTS / ACCOUNTS  (identity is owned by Supabase Auth)
-- ============================================================================

-- Profile row for a guest. Credentials + email verification live in Supabase
-- Auth (auth.users); this row LINKS to that user via auth_user_id.
--   * Locally, auth_user_id is just a UUID column (no FK — auth.users only
--     exists on Supabase).
--   * On Supabase, db/supabase/auth.sql adds the real FK + an auto-insert
--     trigger so this row is created on signup.
create table guests (
    id            uuid primary key default gen_random_uuid(),
    auth_user_id  uuid unique,                 -- -> Supabase auth.users(id) in prod
    full_name     text,
    email         citext unique,               -- mirrors the verified auth email
    phone         text,
    created_at    timestamptz not null default now()
);


-- ============================================================================
-- 3. RESERVATIONS
-- ============================================================================

-- An ENUM restricts a column to a fixed set of values — the DB rejects anything
-- else, so a reservation can never end up in an invalid state like 'banana'.
create type reservation_status as enum
    ('pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled', 'no_show');

create table reservations (
    id                uuid primary key default gen_random_uuid(),
    -- Short human-friendly code the guest sees; unique + auto-generated.
    confirmation_code text not null unique
                        default upper(substr(md5(random()::text), 1, 8)),
    guest_id          uuid not null references guests(id),        -- who booked
    property_id       uuid not null references properties(id),
    room_type_id      uuid not null references room_types(id),
    room_id           uuid references rooms(id),   -- specific room; assigned at check-in
    check_in          date not null,
    check_out         date not null,
    guests_count      smallint not null default 1 check (guests_count > 0),
    status            reservation_status not null default 'pending',
    total_cents       integer check (total_cents >= 0),   -- quoted price (NOT payment)
    currency          char(3) not null default 'USD',
    notes             text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    -- A table-level CHECK: the DB itself guarantees check-out is after check-in.
    constraint chk_dates check (check_out > check_in)
);

-- Indexes make the lookups the Reservation Agent does fast (avoid full scans).
create index idx_res_guest  on reservations (guest_id);
create index idx_res_dates  on reservations (property_id, check_in, check_out);
create index idx_res_status on reservations (status);

-- Full history of status changes. We NEVER hard-delete a booking; a
-- cancellation is a status change plus a row here, so the past stays auditable.
create table reservation_status_history (
    id             bigserial primary key,     -- auto-incrementing integer id
    reservation_id uuid not null references reservations(id) on delete cascade,
    old_status     reservation_status,
    new_status     reservation_status not null,
    changed_by     text not null default 'system',   -- agent name or auth uid
    changed_at     timestamptz not null default now()
);


-- ============================================================================
-- 4. CONVERSATION HISTORY
-- ============================================================================

create table conversations (
    id          uuid primary key default gen_random_uuid(),
    guest_id    uuid references guests(id),   -- NULL for anonymous Q&A sessions
    language    text default 'en',
    created_at  timestamptz not null default now()
);

create table messages (
    id              bigserial primary key,
    conversation_id uuid not null references conversations(id) on delete cascade,
    role            text not null check (role in ('user','assistant','system')),
    content         text not null,
    created_at      timestamptz not null default now()
);
create index idx_msg_conv on messages (conversation_id, created_at);


-- ============================================================================
-- 5. AUDIT LOGS  (agent decisions & compliance outcomes)
-- ============================================================================

-- One reconstructable trail per interaction: every tool call and every
-- compliance approve/reject is written here, linked to the conversation.
create table audit_logs (
    id              bigserial primary key,
    conversation_id uuid references conversations(id) on delete cascade,
    agent           text not null,     -- 'conversation' | 'reservation' | 'compliance'
    event_type      text not null,     -- 'tool_call' | 'compliance_pass' | 'compliance_fail' | 'error'
    policy_ref      text,              -- which policy chunk(s) backed a compliance decision
    payload         jsonb,             -- flexible structured detail
    created_at      timestamptz not null default now()
);
create index idx_audit_conv on audit_logs (conversation_id, created_at);


-- ============================================================================
-- 6. POLICY STORE for RAG  (pgvector)
-- ============================================================================

-- An administrator-curated policy document (cancellation terms, pet policy...).
create table policy_documents (
    id          uuid primary key default gen_random_uuid(),
    title       text not null,
    category    text,                    -- 'cancellation' | 'checkin' | 'pet' | 'faq' ...
    source_uri  text,
    version     integer not null default 1,
    created_at  timestamptz not null default now()
);

-- Each document is split into retrieval-sized chunks. `embedding` is the vector
-- form of `content`; similarity search over it powers the Compliance Agent.
-- vector(1536) matches the text-embedding-3-small model; change the number if
-- you switch embedding models.
create table policy_chunks (
    id           uuid primary key default gen_random_uuid(),
    document_id  uuid not null references policy_documents(id) on delete cascade,
    chunk_index  integer not null,
    content      text not null,
    category     text,                   -- denormalized for fast metadata filtering
    embedding    vector(1536),
    unique (document_id, chunk_index)
);

-- HNSW = an approximate-nearest-neighbour index: finds "closest in meaning"
-- vectors quickly. vector_cosine_ops = compare by cosine similarity.
create index idx_policy_embedding
    on policy_chunks using hnsw (embedding vector_cosine_ops);


-- ============================================================================
-- 7. AVAILABILITY VIEW
-- ============================================================================

-- A VIEW is a saved query that acts like a read-only table. We DERIVE how many
-- rooms a type has rather than storing a counter that could drift out of sync.
create view v_room_type_availability as
select rt.id as room_type_id,
       rt.property_id,
       rt.name,
       count(r.id) filter (where r.is_active) as total_rooms
from room_types rt
join rooms r on r.room_type_id = rt.id
group by rt.id;
