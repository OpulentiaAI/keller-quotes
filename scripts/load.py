#!/usr/bin/env python3
"""Load quotes.csv into the normalized Polygres schema.

Usage: POLYGRES_DIRECT_URL must be set (direct endpoint — DDL + bulk ingest).
       python3 scripts/load.py [path/to/quotes.csv]

Staging COPY -> server-side INSERT..SELECT keeps all dedupe/join logic in SQL.
Idempotent: reruns wipe the staging table and raise on PK conflicts only if the
target rows already exist — run on an empty database or drop + recreate.
"""
import os
import sys

import psycopg

CSV = sys.argv[1] if len(sys.argv) > 1 else "quotes.csv"

STAGE_COLS = (
    "quote_no,item_no,assembly_no,quote_date,date_stamp,customer_id,customer,"
    "part_no,description,rev,drawing_no,rfq_no,buyer_name,salesperson,"
    "quote_letter,letter_date,quantity,unit_price,unit_cost,extended_price,"
    "markup,del_seq,material,status,won_date,to_quote,user_quote,newsellpri,comment"
)


def nz(v: str) -> str | None:
    v = v.strip()
    return v if v else None


def main() -> None:
    url = os.environ["POLYGRES_DIRECT_URL"]
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            create temp table raw_quotes (
              quote_no text, item_no text, assembly_no text, quote_date text,
              date_stamp text, customer_id text, customer text, part_no text,
              description text, rev text, drawing_no text, rfq_no text,
              buyer_name text, salesperson text, quote_letter text,
              letter_date text, quantity text, unit_price text, unit_cost text,
              extended_price text, markup text, del_seq text, material text,
              status text, won_date text, to_quote text, user_quote text,
              newsellpri text, comment text
            ) on commit drop
            """
        )
        with open(CSV, encoding="utf-8") as f, cur.copy(
            f"copy raw_quotes ({STAGE_COLS}) from stdin with (format csv, header true, null '')"
        ) as copy:
            for line in f:
                copy.write(line)
        cur.execute("select count(*) from raw_quotes")
        print("staged:", cur.fetchone()[0])

        # -- customers -----------------------------------------------------
        cur.execute(
            """
            insert into customers (customer_id, customer_name, first_quote, last_quote, quote_count)
            select customer_id,
                   max(nullif(btrim(customer), '')),
                   min(nullif(quote_date, '')::date),
                   max(nullif(quote_date, '')::date),
                   count(distinct quote_no)
            from raw_quotes
            where customer_id <> ''
            group by customer_id
            on conflict (customer_id) do nothing
            """
        )
        print("customers:", cur.rowcount)

        # -- parts ---------------------------------------------------------
        cur.execute(
            """
            insert into parts (part_no, drawing_no, description)
            select distinct
                   coalesce(part_no,''),
                   coalesce(drawing_no,''),
                   coalesce(description,'')
            from raw_quotes
            where btrim(coalesce(part_no,'') || coalesce(drawing_no,'') || coalesce(description,'')) <> ''
            on conflict (part_no, drawing_no, description) do nothing
            """
        )
        print("parts:", cur.rowcount)

        # -- quotes (one row per quote_no; head = first row's fields) --------
        cur.execute(
            """
            insert into quotes (
              quote_no, part_id, customer_id, quote_date, date_stamp, rev,
              rfq_no, buyer_name, salesperson, status, won_date, to_quote,
              comment, assembly_no, item_no, letter_date, has_breaks
            )
            select r.quote_no,
                   p.part_id,
                   nullif(r.customer_id,''),
                   nullif(r.quote_date,'')::date,
                   nullif(r.date_stamp,'')::date,
                   nullif(r.rev,''),
                   nullif(r.rfq_no,''),
                   nullif(r.buyer_name,''),
                   nullif(r.salesperson,''),
                   case when r.status = 'won' then 'won' else 'open' end,
                   nullif(r.won_date,'')::date,
                   null as to_quote,
                   nullif(r.comment,''),
                   nullif(r.assembly_no,''),
                   nullif(r.item_no,''),
                   max(nullif(r.letter_date,''))::date,
                   bool_or(nullif(r.quantity,'') is not null)
            from (select distinct on (quote_no) * from raw_quotes order by quote_no) r
            left join parts p
              on p.part_no = coalesce(r.part_no,'')
             and p.drawing_no = coalesce(r.drawing_no,'')
             and p.description = coalesce(r.description,'')
            group by r.quote_no, p.part_id, r.customer_id, r.quote_date,
                     r.date_stamp, r.rev, r.rfq_no, r.buyer_name, r.salesperson,
                     r.status, r.won_date, r.to_quote, r.comment, r.assembly_no,
                     r.item_no
            on conflict (quote_no) do nothing
            """
        )
        print("quotes:", cur.rowcount)

        # Re-quote lineage: backfill to_quote where the target exists in the
        # dataset ('0000000' = original → stays null; dangling refs stay null).
        cur.execute(
            """
            update quotes q
            set to_quote = nullif(r.to_quote,'0000000')
            from (select distinct on (quote_no) quote_no, to_quote
                  from raw_quotes order by quote_no) r
            where r.quote_no = q.quote_no
              and nullif(r.to_quote,'') is not null
              and nullif(r.to_quote,'0000000') is not null
              and exists (select 1 from quotes p where p.quote_no = r.to_quote)
            """
        )
        print("requote edges:", cur.rowcount)
        cur.execute(
            """
            select count(*) from (select distinct on (quote_no) quote_no, to_quote
              from raw_quotes order by quote_no) r
            where nullif(r.to_quote,'') is not null
              and nullif(r.to_quote,'0000000') is not null
              and not exists (select 1 from quotes p where p.quote_no = r.to_quote)
            """
        )
        dangling = cur.fetchone()[0]
        if dangling:
            print("requote targets not in dataset (kept null):", dangling)

        # -- qty breaks (all source rows; placeholder = no priced break) ----
        cur.execute(
            """
            insert into quote_qty_breaks (
              quote_no, quote_letter, del_seq, quantity, unit_price, unit_cost,
              extended_price, markup, newsellpri, is_placeholder
            )
            select quote_no,
                   nullif(quote_letter,''),
                   nullif(del_seq,'')::int,
                   nullif(quantity,'')::numeric,
                   nullif(unit_price,'')::numeric,
                   nullif(unit_cost,'')::numeric,
                   nullif(extended_price,'')::numeric,
                   nullif(markup,'')::numeric,
                   nullif(newsellpri,'')::numeric,
                   nullif(quantity,'') is null
            from raw_quotes
            """
        )
        print("quote_qty_breaks:", cur.rowcount)

        # -- letters --------------------------------------------------------
        cur.execute(
            """
            insert into quote_letters (quote_letter, letter_date, customer_id, material, quote_count)
            select quote_letter,
                   max(nullif(letter_date,''))::date,
                   (select nullif(customer_id,'') from raw_quotes r2
                     where r2.quote_letter = r.quote_letter and nullif(r2.customer_id,'') is not null
                     limit 1),
                   (select string_agg(distinct m, ' | ') from
                      (select nullif(btrim(material),'') as m from raw_quotes r3
                        where r3.quote_letter = r.quote_letter and nullif(btrim(r3.material),'') is not null) t),
                   count(distinct quote_no)
            from raw_quotes r
            where nullif(quote_letter,'') is not null
            group by quote_letter
            on conflict (quote_letter) do nothing
            """
        )
        print("quote_letters:", cur.rowcount)

        cur.execute(
            """
            insert into quote_letter_lines (quote_letter, quote_no, material)
            select distinct nullif(quote_letter,''), quote_no, nullif(btrim(material),'')
            from raw_quotes
            where nullif(quote_letter,'') is not null
            on conflict (quote_letter, quote_no) do nothing
            """
        )
        print("quote_letter_lines:", cur.rowcount)

        cur.execute(
            """
            select 'customers', count(*) from customers
            union all select 'parts', count(*) from parts
            union all select 'quotes', count(*) from quotes
            union all select 'quotes with breaks', count(*) from quotes where has_breaks
            union all select 'requote edges', count(*) from quotes where to_quote is not null
            union all select 'quote_qty_breaks', count(*) from quote_qty_breaks
            union all select 'placeholders', count(*) from quote_qty_breaks where is_placeholder
            union all select 'quote_letters', count(*) from quote_letters
            union all select 'quote_letter_lines', count(*) from quote_letter_lines
            order by 1
            """
        )
        for row in cur.fetchall():
            print(f"  {row[0]:24} {row[1]:>8}")


if __name__ == "__main__":
    main()
