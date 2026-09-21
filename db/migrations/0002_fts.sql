-- 0002_fts.sql — full-text + trigram index surface.
-- quotes.fts (comment + rfq_no + buyer_name) is a generated column from 0001.
-- parts FTS covers description + part_no + drawing_no.

alter table parts
  add column if not exists fts tsvector
  generated always as (
    to_tsvector('english',
      coalesce(description,'') || ' ' ||
      coalesce(part_no,'')     || ' ' ||
      coalesce(drawing_no,''))
  ) stored;

create index if not exists parts_fts_gin       on parts using gin (fts);
create index if not exists parts_part_no_trgm  on parts using gin (part_no gin_trgm_ops);
create index if not exists parts_drawing_trgm  on parts using gin (drawing_no gin_trgm_ops);
create index if not exists parts_desc_trgm     on parts using gin (description gin_trgm_ops);
create index if not exists customers_name_trgm on customers using gin (customer_name gin_trgm_ops);
create index if not exists quotes_comment_trgm on quotes using gin (comment gin_trgm_ops);
