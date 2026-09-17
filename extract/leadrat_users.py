import os
import json
import time
import requests
import pg8000.dbapi as psycopg2
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

def get_user_list(session, token):
    url = "https://connect.leadrat.com/api/v1/user"
    headers = {"tenant": "valuepersqft", "Authorization": f"Bearer {token}"}
    response = session.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["items"]

def get_user_detail(session, token, user_id):
    url = f"https://connect.leadrat.com/api/v1/user/{user_id}"
    headers = {"tenant": "valuepersqft", "Authorization": f"Bearer {token}"}
    response = session.get(url, headers=headers)
    response.raise_for_status()
    return response.json()["data"]

def main():
    token = get_access_token()
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    session = requests.Session()

    users = get_user_list(session, token)
    print(f"Fetched {len(users)} users from the list endpoint")

    BATCH_SIZE = 25

    for i, user in enumerate(users, start=1):
        cur.execute("""
            INSERT INTO raw.leadrat_users (user_id, payload)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET payload = EXCLUDED.payload, ingested_at = now()
        """, (user["userId"], json.dumps(user)))

        detail = get_user_detail(session, token, user["userId"])
        cur.execute("""
            INSERT INTO raw.leadrat_user_detail (user_id, payload)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET payload = EXCLUDED.payload, ingested_at = now()
        """, (user["userId"], json.dumps(detail)))

        print(f"[{i}/{len(users)}] Saved: {user.get('firstName')} {user.get('lastName')}")

        if i % BATCH_SIZE == 0:
            conn.commit()
            print(f"  -- committed batch through user {i}")

        time.sleep(0.1)

    conn.commit()
    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()