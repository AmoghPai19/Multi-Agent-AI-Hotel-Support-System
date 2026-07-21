-- ============================================================================
--  seed.sql  —  Sample data for local development and A2 acceptance tests
--
--  Uses fixed UUIDs for parent rows so child rows can reference them readably,
--  and dates relative to CURRENT_DATE so "past / current / future" stay valid
--  whenever you run it.
-- ============================================================================

-- ── Property ────────────────────────────────────────────────────────────
insert into properties (id, name, city, timezone) values
  ('11111111-1111-1111-1111-111111111111', 'Seaside Grand Hotel', 'Goa', 'Asia/Kolkata');

-- ── Room types ──────────────────────────────────────────────────────────
insert into room_types (id, property_id, code, name, max_occupancy, base_rate_cents, currency) values
  ('22222222-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'STD',   'Standard Queen', 2, 550000,  'INR'),
  ('22222222-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', 'DLX',   'Deluxe King',    3, 850000,  'INR'),
  ('22222222-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', 'SUITE', 'Sea-View Suite', 4, 1500000, 'INR');

-- ── Rooms (a few per type) ──────────────────────────────────────────────
insert into rooms (room_type_id, room_number, floor) values
  ('22222222-0000-0000-0000-000000000001', '101', 1),
  ('22222222-0000-0000-0000-000000000001', '102', 1),
  ('22222222-0000-0000-0000-000000000001', '103', 1),
  ('22222222-0000-0000-0000-000000000002', '201', 2),
  ('22222222-0000-0000-0000-000000000002', '202', 2),
  ('22222222-0000-0000-0000-000000000003', '301', 3),
  ('22222222-0000-0000-0000-000000000003', '302', 3);
-- Inventory: STD=3 rooms, DLX=2 rooms, SUITE=2 rooms.

-- ── Guests (auth_user_id null locally; set by Supabase Auth in prod) ──────
insert into guests (id, full_name, email, phone) values
  ('33333333-0000-0000-0000-000000000001', 'Amit Rao',    'amit@example.com',  '+91-90000-00001'),
  ('33333333-0000-0000-0000-000000000002', 'Bela Nair',   'bela@example.com',  '+91-90000-00002'),
  ('33333333-0000-0000-0000-000000000003', 'Chetan Shah', 'chetan@example.com','+91-90000-00003');

-- ── Reservations across statuses and dates ───────────────────────────────
-- Two DLX bookings overlap next weekend => used to demonstrate availability math.
insert into reservations
  (guest_id, property_id, room_type_id, check_in, check_out, guests_count, status, total_cents, currency) values
  -- current / future
  ('33333333-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000002',
     current_date + 5, current_date + 8, 2, 'confirmed', 2550000, 'INR'),
  ('33333333-0000-0000-0000-000000000002','11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000002',
     current_date + 6, current_date + 9, 3, 'confirmed', 2550000, 'INR'),
  ('33333333-0000-0000-0000-000000000003','11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000003',
     current_date + 10, current_date + 12, 2, 'pending', 3000000, 'INR'),
  -- past
  ('33333333-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000001',
     current_date - 20, current_date - 17, 1, 'checked_out', 1650000, 'INR'),
  -- cancelled (row stays; frees its dates)
  ('33333333-0000-0000-0000-000000000002','11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000003',
     current_date + 5, current_date + 7, 4, 'cancelled', 3000000, 'INR');

-- ── Sample policy corpus (embeddings added later by the RAG ingestion) ────
insert into policy_documents (id, title, category, version) values
  ('44444444-0000-0000-0000-000000000001', 'Cancellation Policy',      'cancellation', 1),
  ('44444444-0000-0000-0000-000000000002', 'Check-in / Check-out',     'checkin',      1);

insert into policy_chunks (document_id, chunk_index, content, category) values
  ('44444444-0000-0000-0000-000000000001', 0,
     'Free cancellation up to 48 hours before check-in. Within 48 hours, one night is charged.', 'cancellation'),
  ('44444444-0000-0000-0000-000000000002', 0,
     'Check-in is from 2:00 PM. Check-out is by 11:00 AM. Early check-in is subject to availability.', 'checkin');
