import os
import json
import time
import requests
import pg8000.dbapi as psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv
from auth import get_access_token

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT")),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

PAGE_SIZE = 100
MAX_PAGES = 20
BATCH_SIZE = 25


def retry(func, *args, max_retries=3, delay=5, conn=None, **kwargs):
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"  Attempt {attempt}/{max_retries} failed: {e}")
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if attempt == max_retries:
                print("  Giving up after max retries.")
                raise
            print(f"  Waiting {delay} seconds before retrying...")
            time.sleep(delay)


def get_leads_page(session, token, page_number):
    url = "https://connect.leadrat.com/api/v1/lead"
    headers = {"tenant": "valuepersqft", "Authorization": f"Bearer {token}"}
    params = {"PageNumber": page_number, "PageSize": PAGE_SIZE}
    response = session.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def get_lead_detail(session, token, lead_id):
    url = f"https://connect.leadrat.com/api/v1/lead/{lead_id}"
    headers = {"tenant": "valuepersqft", "Authorization": f"Bearer {token}"}
    response = session.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()["data"]


def insert_leads_batch(cur, leads):
    if not leads:
        return
    values_clause = ", ".join(["(%s, %s)"] * len(leads))
    sql = f"""
        INSERT INTO raw.leadrat_leads_list (lead_id, payload)
        VALUES {values_clause}
        ON CONFLICT (lead_id) DO UPDATE SET payload = EXCLUDED.payload, ingested_at = now()
    """
    params = []
    for lead in leads:
        params.append(lead["id"])
        params.append(json.dumps(lead))
    cur.execute(sql, params)


def insert_lead_detail(cur, lead_id, detail):
    cur.execute("""
        INSERT INTO raw.leadrat_lead_detail (lead_id, payload)
        VALUES (%s, %s)
        ON CONFLICT (lead_id) DO UPDATE SET payload = EXCLUDED.payload, ingested_at = now()
    """, (lead_id, json.dumps(detail)))


def get_watermark(cur, source_name):
    cur.execute("SELECT last_synced_at FROM raw.etl_watermark WHERE source_name = %s", (source_name,))
    row = cur.fetchone()
    return row[0] if row else datetime(2000, 1, 1)


def set_watermark(cur, source_name, ts):
    cur.execute("""
        UPDATE raw.etl_watermark SET last_synced_at = %s WHERE source_name = %s
    """, (ts, source_name))


def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SET statement_timeout = '30000'")
    conn.commit()
    return conn, cur


def main():
    token = get_access_token()
    conn, cur = get_db_connection()
    session = requests.Session()

    print(f"Pulling leads list (max {MAX_PAGES} pages)...")
    page_number = 1
    total_leads_pulled = 0
    all_leads = []

    while True:
        fetch_start = time.time()
        data = retry(get_leads_page, session, token, page_number)
        fetch_time = time.time() - fetch_start

        items = data["items"]
        if not items:
            break

        insert_start = time.time()
        retry(insert_leads_batch, cur, items, max_retries=3, delay=3, conn=conn)
        all_leads.extend(items)
        retry(conn.commit, max_retries=3, delay=3, conn=conn)
        insert_time = time.time() - insert_start

        total_leads_pulled += len(items)
        print(f"Page {page_number}: FETCH={fetch_time:.2f}s | INSERT={insert_time:.2f}s | total so far: {total_leads_pulled} of {data.get('totalCount')}")

        if len(items) < PAGE_SIZE:
            break

        page_number += 1
        if MAX_PAGES and page_number > MAX_PAGES:
            print(f"Stopping — MAX_PAGES={MAX_PAGES} reached (test run)")
            break

        time.sleep(0.1)

    print(f"List pull complete: {total_leads_pulled} leads saved to raw.leadrat_leads_list")

    detail_watermark = get_watermark(cur, "leadrat_lead_detail")
    print(f"Detail watermark: leads modified after {detail_watermark} will be pulled")

    leads_needing_detail = [
        lead for lead in all_leads
        if datetime.fromisoformat(lead["lastModifiedOn"].replace("Z", "+00:00")).replace(tzinfo=None) > detail_watermark
    ]
    print(f"{len(leads_needing_detail)} leads need a detail pull")

    detail_start_time = time.time()

    for i, lead in enumerate(leads_needing_detail, start=1):
        detail = retry(get_lead_detail, session, token, lead["id"])
        retry(insert_lead_detail, cur, lead["id"], detail, max_retries=3, delay=3, conn=conn)

        if i % 100 == 0 or i == len(leads_needing_detail):
            elapsed = time.time() - detail_start_time
            print(f"[{i}/{len(leads_needing_detail)}] Detail saved: {lead.get('name')} | elapsed: {elapsed/60:.1f} min")

        if i % BATCH_SIZE == 0:
            retry(conn.commit, max_retries=3, delay=3, conn=conn)

        time.sleep(0.1)

    conn.commit()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    set_watermark(cur, "leadrat_leads_list", now)
    set_watermark(cur, "leadrat_lead_detail", now)
    conn.commit()

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()