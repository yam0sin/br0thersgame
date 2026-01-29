import os
import sqlite3

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "app.db")

# Таблицы, которые обычно хранят "открытия" / инвентарь / заявки
CANDIDATE_TABLES = [
    "drop_history", "drops", "history", "opening_history", "openings",
    "inventory_item", "inventory_items",
    "withdrawal_request", "withdrawals",
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}

    deleted = []
    for t in CANDIDATE_TABLES:
        if t in tables:
            cur.execute(f"DELETE FROM {t};")
            deleted.append(t)

            # сброс автоинкремента (если есть)
            if "sqlite_sequence" in tables:
                cur.execute("DELETE FROM sqlite_sequence WHERE name=?;", (t,))

    conn.commit()
    cur.execute("VACUUM;")
    conn.close()

    print("OK. Cleared tables:", deleted)

if __name__ == "__main__":
    main()
