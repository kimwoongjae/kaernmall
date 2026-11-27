import sqlite3
import os
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "warehouse.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    with conn:
        # 1. 자리(로케이션) 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                code TEXT PRIMARY KEY,
                name TEXT,
                zone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 입고 상품 및 자리 매핑 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_number TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL,
                location_code TEXT NOT NULL,
                status TEXT DEFAULT '보관중',
                worker TEXT DEFAULT '작업자',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (location_code) REFERENCES locations(code)
            )
        """)

        # 3. 스캔 및 이력 로그 테이블
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_number TEXT,
                customer_name TEXT,
                location_code TEXT,
                action TEXT,
                worker TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 기본 샘플 로케이션 생성 (A존, B존 등)
        sample_locs = [
            ("A-01", "A존 1번 선반", "A존"),
            ("A-02", "A존 2번 선반", "A존"),
            ("A-03", "A존 3번 선반", "A존"),
            ("B-01", "B존 1번 선반", "B존"),
            ("B-02", "B존 2번 선반", "B존"),
            ("B-03", "B존 3번 선반", "B존"),
            ("임시보관", "입고 대기 임시구역", "임시"),
        ]
        conn.executemany("""
            INSERT OR IGNORE INTO locations (code, name, zone) VALUES (?, ?, ?)
        """, sample_locs)
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)
