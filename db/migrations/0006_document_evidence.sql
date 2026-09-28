create extension if not exists pgcrypto;

create table if not exists document_corpora (
  corpus_id text primary key check (corpus_id ~ '^[0-9a-f]{64}$'),
  corpus_key bigint generated always as identity unique,
  prepared_manifest jsonb not null,
  manifest_sha256 text not null check (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  csv_sha256 text not null check (csv_sha256 ~ '^[0-9a-f]{64}$'),
  csv_header text not null,
  document_count integer not null check (document_count >= 0),
  page_count integer not null check (page_count >= 0),
  price_count integer not null check (price_count >= 0),
  ingested_at timestamptz not null default now()
);

create table if not exists evidence_documents (
  document_id bigint generated always as identity primary key,
  corpus_key bigint not null references document_corpora(corpus_key),
  source_path text not null,
  pdf_sha256 text not null check (pdf_sha256 ~ '^[0-9a-f]{64}$'),
  pdf_bytes bigint not null check (pdf_bytes >= 0),
  modified_utc timestamptz not null,
  page_count integer not null check (page_count >= 0),
  filename_hint text not null,
  content_kind text not null check (content_kind in ('quote','invoice','packing_slip','supplier_po','certificate','other','unknown')),
  extraction_status text not null check (extraction_status in ('text','blank','failed')),
  anydoc_status text not null check (anydoc_status in ('success','failed','needs_ocr')),
  anydoc_record_sha256 text not null check (anydoc_record_sha256 ~ '^[0-9a-f]{64}$'),
  anydoc_transcript_sha256 text check (anydoc_transcript_sha256 ~ '^[0-9a-f]{64}$'),
  metadata jsonb not null,
  unique (corpus_key, source_path),
  unique (corpus_key, document_id),
  check (source_path !~ '(^/|(^|/)\.\.?/|\\)' and source_path <> ''),
  check ((anydoc_status = 'success') = (anydoc_transcript_sha256 is not null))
);

create function evidence_pages_valid(page_array jsonb)
returns boolean language sql immutable strict as $$
  select jsonb_typeof(page_array) = 'array' and not exists (
    select 1
    from jsonb_array_elements(case when jsonb_typeof(page_array) = 'array' then page_array else '[]'::jsonb end) as page(value)
    where jsonb_typeof(page.value) is distinct from 'object'
       or jsonb_typeof(page.value->'text') is distinct from 'string'
       or jsonb_typeof(page.value->'sha256') is distinct from 'string'
       or (page.value->>'sha256') is distinct from
          encode(digest(convert_to(page.value->>'text', 'UTF8'), 'sha256'), 'hex')
  )
$$;

create table if not exists evidence_page_sets (
  document_id bigint primary key references evidence_documents(document_id),
  pages jsonb not null check (evidence_pages_valid(pages) is true)
) with (toast_tuple_target=512);
create index if not exists evidence_page_sets_fts on evidence_page_sets
  using gin (to_tsvector('english', jsonb_path_query_array(pages, '$[*].text')));

create view evidence_pages as
select s.document_id, page.ordinality::integer as page_number,
       page.value->>'text' as layout_text, page.value->>'sha256' as text_sha256
from evidence_page_sets s
cross join lateral jsonb_array_elements(s.pages) with ordinality as page(value, ordinality);

create table if not exists verified_document_prices (
  corpus_key bigint not null references document_corpora(corpus_key),
  document_id bigint not null,
  quote_no text not null references quotes(quote_no),
  item_no text not null,
  quantity numeric not null check (quantity > 0 and quantity::text not in ('NaN','Infinity','-Infinity') and quantity = trunc(quantity)),
  csv_row_number integer not null check (csv_row_number > 0),
  raw_csv text not null,
  unit_price numeric not null check (unit_price > 0 and unit_price::text not in ('NaN','Infinity','-Infinity') and unit_price = trunc(unit_price, 5)),
  extended_price numeric not null check (extended_price > 0 and extended_price::text not in ('NaN','Infinity','-Infinity') and extended_price = trunc(extended_price, 2)),
  quote_date date not null,
  letter_date date not null,
  part_no text not null,
  customer_id text not null,
  source_price_field text not null check (source_price_field in ('PRICE','QUOTEPRICE')),
  primary key (corpus_key, quote_no, item_no, quantity),
  unique (corpus_key, csv_row_number),
  foreign key (corpus_key, document_id) references evidence_documents(corpus_key, document_id),
  check (extended_price = round(quantity * unit_price, 2))
) with (toast_tuple_target=512);
create index if not exists verified_document_prices_part on verified_document_prices(corpus_key, part_no);
