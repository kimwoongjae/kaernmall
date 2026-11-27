import os
import re
import io
import socket
import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import qrcode
from PIL import Image

import database

app = Flask(__name__)
database.init_db()

def get_local_ip():
    """창고 공유기(LAN/Wi-Fi) 내 현재 PC의 IP 주소 자동 조회"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# --------------------------------------------------------------------------
# 페이지 라우트
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("scanner"))

@app.route("/scanner")
def scanner():
    local_ip = get_local_ip()
    conn = database.get_connection()
    locations = conn.execute("SELECT code, name, zone FROM locations ORDER BY code ASC").fetchall()
    conn.close()
    return render_template("scanner.html", local_ip=local_ip, locations=locations)

@app.route("/inventory")
def inventory():
    conn = database.get_connection()
    locations = conn.execute("SELECT code, name FROM locations ORDER BY code ASC").fetchall()
    conn.close()
    return render_template("inventory.html", locations=locations)

@app.route("/locations")
def locations():
    conn = database.get_connection()
    loc_stats = conn.execute("""
        SELECT l.code, l.name, l.zone,
               COUNT(CASE WHEN i.status = '보관중' THEN 1 END) as active_count
        FROM locations l
        LEFT JOIN items i ON l.code = i.location_code
        GROUP BY l.code
        ORDER BY l.code ASC
    """).fetchall()
    conn.close()
    return render_template("locations.html", locations=loc_stats)

# --------------------------------------------------------------------------
# QR 코드 실시간 이미지 생성 라우트
# --------------------------------------------------------------------------
@app.route("/qr/<path:text>")
def generate_qr(text):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# --------------------------------------------------------------------------
# REST API
# --------------------------------------------------------------------------
def is_location_qr(text, conn):
    """장소 QR 코드인지 판별 (LOC: 접두어 또는 A-110 규격 또는 DB 등록여부)"""
    cleaned = text.strip().upper()
    if cleaned.startswith("LOC:"):
        cleaned = cleaned[4:].strip()

    # A-110, B-321 등 사용자 규격 패턴 검사
    if re.match(r'^[AB]-[1-5]\d{2}$', cleaned):
        return True, cleaned

    # DB에 등록된 자리인지 검사
    row = conn.execute("SELECT code, name FROM locations WHERE code = ?", (cleaned,)).fetchone()
    if row:
        return True, row["code"]

    return False, ""

@app.route("/api/scan", methods=["POST"])
def api_scan():
    """
    지능형 양방향 스캔 API:
    1. 상품 라벨 먼저 스캔 -> 장소 스캔 시 자동 저장!
    2. 장소 먼저 스캔 -> 상품 라벨 스캔 시 자동 저장!
    3. 연속 상품 스캔 가능!
    """
    data = request.json or {}
    scanned_text = data.get("qr_text", "").strip()
    current_location = data.get("location", "").strip()
    worker = data.get("worker", "작업자").strip() or "작업자"
    pending_items = data.get("pending_items", []) # 상품 먼저 스캔 시 대기 중인 상품 목록
    pending_customer = data.get("pending_customer", "고객")

    if not scanned_text:
        return jsonify({"success": False, "message": "스캔된 데이터가 없습니다."}), 400

    conn = database.get_connection()

    # 1. 스캔된 텍스트가 [장소(로케이션) QR] 인지 판정
    is_loc, loc_code = is_location_qr(scanned_text, conn)

    if is_loc:
        # 장소 정보 조회/생성
        loc_row = conn.execute("SELECT code, name, zone FROM locations WHERE code = ?", (loc_code,)).fetchone()
        if not loc_row:
            # 규격에 맞으나 DB에 아직 없으면 자동 등록
            loc_name, loc_zone = database.parse_location_name(loc_code)
            with conn:
                conn.execute("INSERT OR IGNORE INTO locations (code, name, zone) VALUES (?, ?, ?)", (loc_code, loc_name, loc_zone))
            loc_row = {"code": loc_code, "name": loc_name, "zone": loc_zone}

        # 만약 이미 스캔해 둔 대기 상품(pending_items)이 있다면 ➡️ 장소 스캔 즉시 자동 저장!
        if pending_items and len(pending_items) > 0:
            saved_items = []
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with conn:
                for num in pending_items:
                    num_str = str(num).strip()
                    existing = conn.execute("SELECT * FROM items WHERE item_number = ?", (num_str,)).fetchone()
                    if existing:
                        conn.execute("""
                            UPDATE items
                            SET customer_name = ?, location_code = ?, status = '보관중', worker = ?, updated_at = ?
                            WHERE item_number = ?
                        """, (pending_customer, loc_code, worker, now_str, num_str))
                        action_text = f"자리이동 ({existing['location_code']} ➡️ {loc_code})"
                    else:
                        conn.execute("""
                            INSERT INTO items (item_number, customer_name, location_code, status, worker, created_at, updated_at)
                            VALUES (?, ?, ?, '보관중', ?, ?, ?)
                        """, (num_str, pending_customer, loc_code, worker, now_str, now_str))
                        action_text = f"신규입고 ({loc_code})"

                    conn.execute("""
                        INSERT INTO scan_logs (item_number, customer_name, location_code, action, worker, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (num_str, pending_customer, loc_code, action_text, worker, now_str))

                    saved_items.append({
                        "item_number": num_str,
                        "customer_name": pending_customer,
                        "location": loc_code,
                        "action": action_text,
                        "time": now_str
                    })

            conn.close()
            return jsonify({
                "success": True,
                "type": "auto_matched_saved",
                "items": saved_items,
                "count": len(saved_items),
                "customer": pending_customer,
                "location": loc_code,
                "location_name": loc_row["name"],
                "message": f"🎉 {pending_customer} ({len(saved_items)}건) ➡️ [{loc_code}]에 자동 매칭 저장 완료!"
            })

        # 대기 상품이 없으면 장소 지정
        conn.close()
        return jsonify({
            "success": True,
            "type": "location_set",
            "location_code": loc_row["code"],
            "location_name": loc_row["name"],
            "message": f"📍 보관 장소가 '{loc_row['code']}'({loc_row['name']})로 설정되었습니다."
        })

    # 2. 스캔된 텍스트가 [상품 라벨지 QR] 인 경우
    lines = [line.strip() for line in scanned_text.splitlines() if line.strip()]
    numbers = []
    customer_name = "고객"

    for line in lines:
        cleaned_num = re.sub(r'[^0-9]', '', line)
        if cleaned_num and 4 <= len(cleaned_num) <= 10:
            numbers.append(cleaned_num)
        else:
            name_cand = re.sub(r'[\r\n\t]+', '', line).strip()
            if name_cand and not name_cand.startswith("http") and not name_cand.upper().startswith("LOC:"):
                customer_name = name_cand

    if not numbers:
        found_nums = re.findall(r'\b\d{6,8}\b', scanned_text)
        if found_nums:
            numbers = found_nums

    if not numbers:
        conn.close()
        return jsonify({"success": False, "message": "스캔 내용에서 상품 번호를 찾을 수 없습니다."}), 400

    # 만약 현재 지정된 장소가 있다면 ➡️ 바로 저장!
    if current_location:
        saved_items = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with conn:
            for num in numbers:
                existing = conn.execute("SELECT * FROM items WHERE item_number = ?", (num,)).fetchone()
                if existing:
                    conn.execute("""
                        UPDATE items
                        SET customer_name = ?, location_code = ?, status = '보관중', worker = ?, updated_at = ?
                        WHERE item_number = ?
                    """, (customer_name, current_location, worker, now_str, num))
                    action_text = f"자리이동 ({existing['location_code']} ➡️ {current_location})"
                else:
                    conn.execute("""
                        INSERT INTO items (item_number, customer_name, location_code, status, worker, created_at, updated_at)
                        VALUES (?, ?, ?, '보관중', ?, ?, ?)
                    """, (num, customer_name, current_location, worker, now_str, now_str))
                    action_text = f"신규입고 ({current_location})"

                conn.execute("""
                    INSERT INTO scan_logs (item_number, customer_name, location_code, action, worker, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (num, customer_name, current_location, action_text, worker, now_str))

                saved_items.append({
                    "item_number": num,
                    "customer_name": customer_name,
                    "location": current_location,
                    "action": action_text,
                    "time": now_str
                })

        conn.close()
        return jsonify({
            "success": True,
            "type": "item_saved",
            "items": saved_items,
            "count": len(saved_items),
            "customer": customer_name,
            "location": current_location,
            "message": f"✅ {customer_name} ({len(saved_items)}건) ➡️ [{current_location}] 저장 완료!"
        })

    # 만약 지정된 장소가 없다면 ➡️ 상품 대기 상태로 반환 (장소 스캔 유도)
    conn.close()
    return jsonify({
        "success": True,
        "type": "item_pending",
        "pending_items": numbers,
        "pending_customer": customer_name,
        "count": len(numbers),
        "message": f"📦 상품 인식: {customer_name} ({len(numbers)}건) ➡️ 이제 선반의 [장소 QR]을 스캔하세요!"
    })

@app.route("/api/inventory", methods=["GET"])
def api_inventory():
    query = request.args.get("q", "").strip()
    status = request.args.get("status", "보관중").strip()
    location = request.args.get("location", "").strip()

    sql = "SELECT * FROM items WHERE 1=1"
    params = []

    if status and status != "전체":
        sql += " AND status = ?"
        params.append(status)

    if location:
        sql += " AND location_code = ?"
        params.append(location)

    if query:
        sql += " AND (item_number LIKE ? OR customer_name LIKE ? OR worker LIKE ?)"
        wildcard = f"%{query}%"
        params.extend([wildcard, wildcard, wildcard])

    sql += " ORDER BY updated_at DESC LIMIT 500"

    conn = database.get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    items = [dict(row) for row in rows]
    return jsonify({"success": True, "items": items, "count": len(items)})

@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    data = request.json or {}
    item_num = data.get("item_number", "")
    worker = data.get("worker", "작업자")

    conn = database.get_connection()
    with conn:
        conn.execute("""
            UPDATE items SET status = '출고완료', worker = ?, updated_at = CURRENT_TIMESTAMP
            WHERE item_number = ?
        """, (worker, item_num))
        conn.execute("""
            INSERT INTO scan_logs (item_number, action, worker)
            VALUES (?, '출고완료', ?)
        """, (item_num, worker))
    conn.close()
    return jsonify({"success": True, "message": f"{item_num} 출고 처리 완료"})

@app.route("/api/locations/add", methods=["POST"])
def api_locations_add():
    data = request.json or {}
    zone_val = data.get("zone", "A").strip().upper()
    rack_val = data.get("rack", "1").strip()
    floor_val = data.get("floor", "1").strip()
    box_val = data.get("box", "0").strip()

    code = f"{zone_val}-{rack_val}{floor_val}{box_val}"
    name, zone = database.parse_location_name(code)

    conn = database.get_connection()
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO locations (code, name, zone) VALUES (?, ?, ?)", (code, name, zone))
        conn.close()
        return jsonify({"success": True, "code": code, "name": name, "message": f"자리 '{code}' ({name}) 추가 완료"})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 400

@app.route("/api/locations/generate_standard", methods=["POST"])
def api_locations_generate_standard():
    """A구역, B구역 1~5번 렉 (1~4층) 표준 세트 일괄 생성"""
    conn = database.get_connection()
    count = 0
    with conn:
        for zone_char in ['A', 'B']:
            for rack_num in range(1, 6): # 100~500번 렉
                for floor_num in range(1, 5): # 1~4층
                    code = f"{zone_char}-{rack_num}{floor_num}0"
                    name, zone = database.parse_location_name(code)
                    conn.execute("INSERT OR IGNORE INTO locations (code, name, zone) VALUES (?, ?, ?)", (code, name, zone))
                    count += 1
    conn.close()
    return jsonify({"success": True, "message": f"표준 보관장소 {count}개 일괄 생성 완료!"})

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print(f"📦 [카에루몰 스마트 창고 로케이션 시스템 서버 시작]")
    print(f"🖥️ PC 접속 주소:     http://localhost:{port}")
    print(f"📱 스마트폰 접속 주소: http://{local_ip}:{port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
