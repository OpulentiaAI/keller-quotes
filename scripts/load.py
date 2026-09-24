#!/usr/bin/env python3
"""Transactionally refresh the quotes present in a CSV in the Polygres mirror.

Usage: POLYGRES_DIRECT_URL=... python3 scripts/load.py [path/to/quotes.csv]
Only quote numbers in the input are replaced; other quotes and estimates remain.
"""
import csv
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


def main() -> None:
    with open(CSV, encoding="utf-8-sig", newline="") as source:
        header = next(csv.reader(source), None)
    if header != STAGE_COLS.split(","):
        raise ValueError("CSV header must exactly match the canonical quote register columns and order")
    with psycopg.connect(os.environ["POLYGRES_DIRECT_URL"]) as conn, conn.cursor() as cur:
        cur.execute("select pg_advisory_xact_lock(57841433)")
        cur.execute(
            """create temp table raw_quotes (
              source_row bigint generated always as identity,
              quote_no text, item_no text, assembly_no text, quote_date text,
              date_stamp text, customer_id text, customer text, part_no text,
              description text, rev text, drawing_no text, rfq_no text,
              buyer_name text, salesperson text, quote_letter text,
              letter_date text, quantity text, unit_price text, unit_cost text,
              extended_price text, markup text, del_seq text, material text,
              status text, won_date text, to_quote text, user_quote text,
              newsellpri text, comment text
            ) on commit drop"""
        )
        with open(CSV, encoding="utf-8", newline="") as source, cur.copy(
            f"copy raw_quotes ({STAGE_COLS}) from stdin with (format csv, header true, null '')"
        ) as copy:
            for line in source:
                copy.write(line)
        cur.execute("select count(*) from raw_quotes")
        print("staged:", cur.fetchone()[0])
        cur.execute("select count(*) from raw_quotes where nullif(btrim(quote_no), '') is null")
        if cur.fetchone()[0]:
            raise ValueError("CSV contains a blank quote_no")

        cur.execute("create index on raw_quotes (quote_no)")
        cur.execute("create temp table incoming as select distinct on (quote_no) * from raw_quotes order by quote_no, source_row")
        cur.execute("create unique index on incoming (quote_no)")
        cur.execute("create temp table affected_customers (customer_id text primary key) on commit drop")
        cur.execute("""insert into affected_customers
                       select customer_id from quotes where quote_no in (select quote_no from incoming)
                         and customer_id is not null
                       union select customer_id from incoming
                       where nullif(customer_id, '') is not null""")
        cur.execute("create temp table affected_letters (quote_letter text primary key) on commit drop")
        cur.execute("""insert into affected_letters
                       select quote_letter from quote_letter_lines where quote_no in (select quote_no from incoming)
                       union select quote_letter from raw_quotes where nullif(quote_letter, '') is not null""")

        cur.execute("""insert into customers (customer_id)
                       select customer_id from affected_customers
                       on conflict (customer_id) do nothing""")
        cur.execute("""insert into parts (part_no, drawing_no, description)
                       select distinct coalesce(part_no,''), coalesce(drawing_no,''), coalesce(description,'')
                       from incoming
                       where btrim(coalesce(part_no,'') || coalesce(drawing_no,'') || coalesce(description,'')) <> ''
                       on conflict (part_no, drawing_no, description) do nothing""")
        cur.execute("""insert into quotes (
                         quote_no, part_id, customer_id, quote_date, date_stamp, rev,
                         rfq_no, buyer_name, salesperson, status, won_date, comment,
                         assembly_no, item_no, letter_date, has_breaks)
                       select r.quote_no, p.part_id, nullif(r.customer_id,''),
                              nullif(r.quote_date,'')::date, nullif(r.date_stamp,'')::date,
                              nullif(r.rev,''), nullif(r.rfq_no,''), nullif(r.buyer_name,''),
                              nullif(r.salesperson,''),
                              case when r.status = 'won' then 'won' else 'open' end,
                              nullif(r.won_date,'')::date, nullif(r.comment,''),
                              nullif(r.assembly_no,''), nullif(r.item_no,''),
                              (select max(nullif(d.letter_date,'')::date) from raw_quotes d
                               where d.quote_no = r.quote_no),
                              exists (select 1 from raw_quotes d where d.quote_no = r.quote_no
                                      and nullif(d.quantity,'') is not null)
                       from incoming r
                       left join parts p on p.part_no = coalesce(r.part_no,'')
                         and p.drawing_no = coalesce(r.drawing_no,'')
                         and p.description = coalesce(r.description,'')
                       on conflict (quote_no) do update set
                         part_id = excluded.part_id, customer_id = excluded.customer_id,
                         quote_date = excluded.quote_date, date_stamp = excluded.date_stamp,
                         rev = excluded.rev, rfq_no = excluded.rfq_no,
                         buyer_name = excluded.buyer_name, salesperson = excluded.salesperson,
                         status = excluded.status, won_date = excluded.won_date,
                         comment = excluded.comment, assembly_no = excluded.assembly_no,
                         item_no = excluded.item_no, letter_date = excluded.letter_date,
                         has_breaks = excluded.has_breaks,
                         comment_embedding = case when quotes.comment is distinct from excluded.comment
                                                  then null else quotes.comment_embedding end
                       where (quotes.part_id, quotes.customer_id, quotes.quote_date, quotes.date_stamp,
                              quotes.rev, quotes.rfq_no, quotes.buyer_name, quotes.salesperson,
                              quotes.status, quotes.won_date, quotes.comment, quotes.assembly_no,
                              quotes.item_no, quotes.letter_date, quotes.has_breaks) is distinct from
                             (excluded.part_id, excluded.customer_id, excluded.quote_date, excluded.date_stamp,
                              excluded.rev, excluded.rfq_no, excluded.buyer_name, excluded.salesperson,
                              excluded.status, excluded.won_date, excluded.comment, excluded.assembly_no,
                              excluded.item_no, excluded.letter_date, excluded.has_breaks)""")
        print("quotes inserted/changed:", cur.rowcount)
        cur.execute("""update quotes q set to_quote = resolved.target
                       from (select r.quote_no,
                                    case when r.to_quote not in ('', '0000000')
                                           and p.quote_no is not null then p.quote_no end as target
                             from incoming r left join quotes p on p.quote_no = r.to_quote) resolved
                       where q.quote_no = resolved.quote_no
                         and q.to_quote is distinct from resolved.target""")
        print("requote edges changed:", cur.rowcount)

        cur.execute("delete from quote_qty_breaks where quote_no in (select quote_no from incoming)")
        cur.execute("""insert into quote_qty_breaks (
                         quote_no, quote_letter, del_seq, quantity, unit_price, unit_cost,
                         extended_price, markup, newsellpri, is_placeholder)
                       select quote_no, nullif(quote_letter,''), nullif(del_seq,'')::int,
                              nullif(quantity,'')::numeric, nullif(unit_price,'')::numeric,
                              nullif(unit_cost,'')::numeric, nullif(extended_price,'')::numeric,
                              nullif(markup,'')::numeric, nullif(newsellpri,'')::numeric,
                              nullif(quantity,'') is null
                       from raw_quotes order by source_row""")
        print("quote_qty_breaks refreshed:", cur.rowcount)

        cur.execute("delete from quote_letter_lines where quote_no in (select quote_no from incoming)")
        cur.execute("""insert into quote_letters (quote_letter)
                       select quote_letter from affected_letters
                       on conflict (quote_letter) do nothing""")
        cur.execute("""insert into quote_letter_lines (quote_letter, quote_no, material, letter_date)
                       select quote_letter, quote_no,
                              string_agg(distinct nullif(btrim(material), ''), ' | '
                                         order by nullif(btrim(material), '')),
                              max(nullif(letter_date, '')::date)
                       from raw_quotes where nullif(quote_letter, '') is not null
                       group by quote_letter, quote_no""")
        cur.execute("""update quote_letters l set
                         quote_count = summary.quote_count,
                         letter_date = case when summary.unknown_dates = 0 then summary.letter_date
                                            else l.letter_date end,
                         customer_id = summary.customer_id,
                         material = summary.material
                       from (select a.quote_letter, count(distinct x.quote_no) as quote_count,
                                    max(x.letter_date) as letter_date,
                                    count(x.quote_no) filter (where x.letter_date is null) as unknown_dates,
                                    (array_agg(q.customer_id order by q.quote_date desc nulls last,
                                                            x.quote_no desc)
                                     filter (where q.customer_id is not null))[1] as customer_id,
                                    (select string_agg(m.value, ' | ' order by m.value)
                                     from (select distinct btrim(value) as value
                                           from quote_letter_lines line,
                                                unnest(string_to_array(line.material, ' | ')) value
                                           where line.quote_letter = a.quote_letter
                                             and nullif(btrim(value), '') is not null) m) as material
                             from affected_letters a
                             left join quote_letter_lines x on x.quote_letter = a.quote_letter
                             left join quotes q on q.quote_no = x.quote_no
                             group by a.quote_letter) summary
                       where l.quote_letter = summary.quote_letter""")
        cur.execute("""delete from quote_letters l where l.quote_letter in (select quote_letter from affected_letters)
                       and not exists (select 1 from quote_letter_lines x where x.quote_letter = l.quote_letter)""")

        cur.execute("""update customers c set
                         first_quote = summary.first_quote, last_quote = summary.last_quote,
                         quote_count = summary.quote_count,
                         customer_name = case when summary.quote_count = 0 then null
                                              when named.customer is not null and
                                                coalesce(named.letter_date, '-infinity'::date) >=
                                                coalesce((select max(l.letter_date) from quote_letters l
                                                          where l.customer_id = c.customer_id), '-infinity'::date)
                                                then named.customer
                                              else c.customer_name end
                       from (select a.customer_id, min(q.quote_date) as first_quote,
                                    max(q.quote_date) as last_quote, count(q.quote_no) as quote_count
                             from affected_customers a left join quotes q on q.customer_id = a.customer_id
                             group by a.customer_id) summary
                       left join lateral (
                         select nullif(btrim(r.customer), '') as customer,
                                nullif(r.letter_date, '')::date as letter_date
                         from raw_quotes r where r.customer_id = summary.customer_id
                           and nullif(r.quote_letter, '') is not null
                           and nullif(btrim(r.customer), '') is not null
                         order by nullif(r.letter_date, '')::date desc nulls last,
                                  r.quote_no desc, r.source_row desc limit 1
                       ) named on true
                       where c.customer_id = summary.customer_id""")
        cur.execute("""delete from customers c where c.customer_id in (select customer_id from affected_customers)
                       and c.quote_count = 0
                       and not exists (select 1 from quote_letters l where l.customer_id = c.customer_id)
                       and not exists (select 1 from estimates e where e.customer_id = c.customer_id)""")
    print("refresh committed")


if __name__ == "__main__":
    main()
