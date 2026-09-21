-- 0004_embeddings.sql — pgContext collections over the populated tables.
-- Run AFTER data load: collections bind a source table, register_vector binds
-- the pgcontext.vector column, backfill_points registers every row's key.
-- Points consume embedding budget only for rows whose vector column is
-- populated — embed first (scripts/embed.py), then upsert those keys.
-- 512 dims cosine. Scores returned by pgcontext.search are cosine DISTANCE
-- (0 = identical), not similarity.

select * from pgcontext.create_collection('parts_desc', 'public.parts');
select * from pgcontext.register_vector('parts_desc', 'desc_emb', 'embedding', 512, 'cosine');

select * from pgcontext.create_collection('quote_comments', 'public.quotes');
select * from pgcontext.register_vector('quote_comments', 'comment_emb', 'comment_embedding', 512, 'cosine');

-- scripts/embed.py upserts points for exactly the rows it embedded:
--   select * from pgcontext.upsert_points('parts_desc', array[<part_id as text>...])
--   select * from pgcontext.upsert_points('quote_comments', array[<quote_no>...])
-- (backfill_points registers ALL rows — only use it if every row has a vector.)
