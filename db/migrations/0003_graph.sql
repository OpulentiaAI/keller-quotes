-- 0003_graph.sql — register the quoting model with the `graph` extension.
-- Nodes: customers, parts, quotes  (letters stay relational — Nano graph-unit
-- budget; they are headers, not traversal targets).
-- Edges: customer->QUOTED->quote, quote->FOR_PART->part, quote->REQUOTE_OF->quote.
-- As built: 78,460 nodes + 90,030 edges ≈ 87,463 units (< 100k Nano cap).
--
-- Ordering note: graph.build() executes as internal role `graph_sync_owner`,
-- which needs access to the node tables — grant BEFORE building.
-- Trigger-based sync captures whole-row images into graph._sync_log; bulk
-- vector updates (scripts/embed.py) inflate it. Either run embeddings before
-- this migration, or drain after:
--   select * from graph.apply_sync();  delete from graph._sync_log;

grant all on customers, parts, quotes to graph_sync_owner;

select graph.add_table('customers'::regclass, 'customer_id',
       array['customer_name','quote_count','first_quote','last_quote']);

select graph.add_table('parts'::regclass, 'part_id',
       array['part_no','drawing_no','description']);

select graph.add_table('quotes'::regclass, 'quote_no',
       array['quote_date','status','customer_id','to_quote']);

select graph.add_edge('quotes'::regclass, 'customer_id',
       'customers'::regclass, 'customer_id', 'QUOTED', false);

select graph.add_edge('quotes'::regclass, 'part_id',
       'parts'::regclass, 'part_id', 'FOR_PART', false);

select graph.add_edge('quotes'::regclass, 'to_quote',
       'quotes'::regclass, 'quote_no', 'REQUOTE_OF', false);

select graph.build();
