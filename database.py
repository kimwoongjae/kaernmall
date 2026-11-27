import sqlite3
import os
import re
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "warehouse.db")

def parse_location_name(code):
    """
    보관장소 코드 체계 (A-110, B-321 등)
    - 구역: A, B
    - 100번대: 1~5번 렉 (100~500)
    - 10번대: 1~5층 (10, 20, 30, 40, 50)
    - 1번대: 0은 통선반, 1~9는 층 내 세부 박스 번호
    """
    code_clean = code.strip().upper()
    if code_clean.startswith("LOC:"):
        code_clean = code_clean[4:].strip()

    m = re.match(r'^([AB])-([1-5])([1-5])(\d)$', code_clean)
    if m:
        zone = f"{m.group(1)}구역"
        rack = f"{m.group(2)}번 렉"
        floor = f"{m.group(3)}층"
        box_num = int(m.group(4))
        box = f" ({box_num}번 박스)" if box_num > 0 else ""
        return f"{zone} {rack} {floor}{box}", f"{m.group(1)}구역"

    return code_clean, "기타"

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

        # 구버전 임시 자리들 정리
        conn.execute("DELETE FROM locations WHERE code IN ('A-01', 'A-02', 'A-03', 'B-01', 'B-02', 'B-03', '임시보관')")

        # 표준 자리 생성 (A, B구역 / 1~5번 렉 / 1~5층 / 0~3번 박스)
        standard_locations = []
        for zone_char in ['A', 'B']:
            for rack_num in range(1, 6): # 100 ~ 500번 렉
                for floor_num in range(1, 6): # 1 ~ 5층 (10번대는 5까지)
                    for box_num in [0, 1, 2, 3]: # 1번대 (0은 통선반, 1~3번 박스)
                        code = f"{zone_char}-{rack_num}{floor_num}{box_num}"
                        name, zone = parse_location_name(code)
                        standard_locations.append((code, name, zone))

        conn.executemany("""
            INSERT OR IGNORE INTO locations (code, name, zone) VALUES (?, ?, ?)
        """, standard_locations)

    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
