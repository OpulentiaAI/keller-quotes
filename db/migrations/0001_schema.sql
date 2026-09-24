-- 0001_schema.sql — normalized FabriTRAK quoting model on Polygres.
-- Apply with the DIRECT endpoint (DDL): psql "$POLYGRES_DIRECT_URL" -f 0001_schema.sql
-- Vector columns use pgContext's native pgcontext.vector type (the pgvector
-- extension is superuser-gated on Polygres; pgcontext.vector works under the
-- project_owner role and feeds the managed embedding layer).
-- Nano tier note: letters are NOT graph nodes — they stay relational to keep
-- graph units under the 100k cap.

create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists pg_trgm;    -- fuzzy text lookup

-- ---------------------------------------------------------------------------
-- customers: one row per COMP_ID. customer_name is resolved for ids that ever
-- appeared on a quote letter (COMPTO / COMPDICT coverage); the rest keep id only.
create table if not exists customers (
  customer_id   text primary key,
  customer_name text,
  first_quote   date,
  last_quote    date,
  quote_count   int not null default 0
);

-- ---------------------------------------------------------------------------
-- parts: deduped across all quotes on (part_no, drawing_no, description).
-- rev lineage stays on quotes (rev is per-quote-revision, not per-part).
-- embedding: 512-dim pgContext vector over description text — populated by the
-- embedding pipeline, not at insert time.
create table if not exists parts (
  part_id      bigint generated always as identity primary key,
  id           text generated always as (part_id::text) stored,  -- pgContext source key
  part_no      text not null,
  drawing_no   text not null default '',
  description  text not null default '',
  embedding    pgcontext.vector(512),
  unique (part_no, drawing_no, description)
);

-- ---------------------------------------------------------------------------
-- quotes: one row per QUOTE_NO (head of QUOTLINE grains).
-- quote_date = ORG_DATE (real quote date); date_stamp = last touch — they
-- diverge on revisions. status is 'won' | 'open' ONLY: FabriTRAK's QUOTEHN
-- (dead quotes) is empty on this register, so open silently includes lost.
-- to_quote is a self-FK: '0000000' means original, anything else re-quotes
-- the referenced quote_no. comment is verbatim free text incl. CRLF.
create table if not exists quotes (
  quote_no     text primary key,
  id           text generated always as (quote_no) stored,  -- pgContext source key
  part_id      bigint references parts(part_id),
  customer_id  text references customers(customer_id),
  quote_date   date,
  date_stamp   date,
  rev          text,
  rfq_no       text,
  buyer_name   text,
  salesperson  text,
  status       text not null default 'open'
               check (status in ('won','open')),
  won_date     date,
  to_quote     text references quotes(quote_no),
  comment      text,
  comment_embedding pgcontext.vector(512),
  assembly_no  text,
  item_no      text,
  letter_date  date,
  has_breaks   boolean not null default false,
  fts tsvector generated always as (
    to_tsvector('english',
      coalesce(comment,'')   || ' ' ||
      coalesce(rfq_no,'')    || ' ' ||
      coalesce(buyer_name,''))
  ) stored
);

create index if not exists quotes_customer    on quotes(customer_id);
create index if not exists quotes_part        on quotes(part_id);
create index if not exists quotes_to_quote    on quotes(to_quote) where to_quote is not null;
create index if not exists quotes_status      on quotes(status);
create index if not exists quotes_quote_date  on quotes(quote_date);
create index if not exists quotes_fts         on quotes using gin (fts);

-- ---------------------------------------------------------------------------
-- quote_qty_breaks: one row per source CSV row (177,398 priced breaks).
-- Quotes with no priced breaks produce a single is_placeholder row so the
-- 179,608-row grain of quotes.csv is preserved explicitly, never dropped.
create table if not exists quote_qty_breaks (
  break_id       bigint generated always as identity primary key,
  quote_no       text not null references quotes(quote_no),
  quote_letter   text,
  del_seq        int,
  quantity       numeric(14,2),
  unit_price     numeric(14,6),
  unit_cost      numeric(14,6),
  extended_price numeric(16,4),
  markup         numeric(10,4),
  newsellpri     numeric(14,6),
  is_placeholder boolean not null default false
);

create index if not exists qqb_quote    on quote_qty_breaks(quote_no);
create index if not exists qqb_letter   on quote_qty_breaks(quote_letter);
create index if not exists qqb_price    on quote_qty_breaks(quote_no, quantity)
  where not is_placeholder;

-- ---------------------------------------------------------------------------
-- quote_letters: QUOTLETT — a letter groups quotes sent to a customer.
-- material is sparse and only ever arrives via letter lines; kept verbatim.
create table if not exists quote_letters (
  quote_letter text primary key,
  letter_date  date,
  customer_id  text references customers(customer_id),
  material     text,
  quote_count  int not null default 0
);

-- letter → quote linkage (many quotes per letter; material per line)
create table if not exists quote_letter_lines (
  quote_letter text not null references quote_letters(quote_letter),
  quote_no     text not null references quotes(quote_no),
  material     text,
  letter_date  date,
  primary key (quote_letter, quote_no)
);

-- ---------------------------------------------------------------------------
-- estimates / estimate_lines: the estimator's OWN output — request-id keyed,
-- never mixed with real quoted history.
create table if not exists estimates (
  estimate_id  uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  request_id   text,
  customer     text,
  customer_id  text references customers(customer_id),
  request      jsonb not null,
  total        numeric(16,4),
  jev_enabled  boolean not null default false,
  register_rows int
);
create index if not exists estimates_request on estimates(request_id) where request_id is not null;

create table if not exists estimate_lines (
  line_id       bigint generated always as identity primary key,
  estimate_id   uuid not null references estimates(estimate_id) on delete cascade,
  part          jsonb not null,          -- {part_no, drawing_no, description, quantity, material}
  unit_price    numeric(14,6),
  extended_price numeric(16,4),
  price_low     numeric(14,6),           -- p25
  price_high    numeric(14,6),           -- p75
  confidence    numeric(4,3),
  method        text,                    -- interpolate | nearest_break | analog_only
  status_basis  text,                    -- which statuses fed the analog pool
  analogs       jsonb,                   -- [{quote_no, rank_prob, ...}]
  warnings      text[]
);
