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
@app.route("/api/scan", methods=["POST"])
def api_scan():
    """
    모바일 스캔 데이터 수신 및 파싱/저장
    - 라벨 QR 텍스트:
      줄바꿈으로 번호들과 마지막에 고객명이 들어옴 (예: 1124833\n1124834\n김소영)
    - 또는 단건: 1123531\n조정인
    - 자리 QR인 경우: code가 들어오거나 'LOC:A-01' 형태
    """
    data = request.json or {}
    scanned_text = data.get("qr_text", "").strip()
    current_location = data.get("location", "").strip()
    worker = data.get("worker", "작업자").strip() or "작업자"

    if not scanned_text:
        return jsonify({"success": False, "message": "스캔된 데이터가 없습니다."}), 400

    conn = database.get_connection()

    # 1. 자리(로케이션) QR인지 판정
    # 'LOC:A-01' 또는 등록된 자리 코드인 경우
    loc_code = scanned_text
    if loc_code.upper().startswith("LOC:"):
        loc_code = loc_code[4:].strip()

    loc_exists = conn.execute("SELECT code, name FROM locations WHERE code = ?", (loc_code,)).fetchone()
    if loc_exists or scanned_text.upper().startswith("LOC:"):
        conn.close()
        return jsonify({
            "success": True,
            "type": "location_set",
            "location_code": loc_exists["code"] if loc_exists else loc_code,
            "location_name": loc_exists["name"] if loc_exists else loc_code,
            "message": f"📍 자리 '{loc_exists['code'] if loc_exists else loc_code}'(으)로 설정되었습니다."
        })

    # 2. 상품 라벨지 QR 파싱
    if not current_location:
        conn.close()
        return jsonify({
            "success": False,
            "message": "⚠️ 먼저 자리를 지정하거나 자리 QR코드를 먼저 스캔해주세요!"
        }), 400

    lines = [line.strip() for line in scanned_text.splitlines() if line.strip()]
    numbers = []
    customer_name = "고객"

    for line in lines:
        cleaned_num = re.sub(r'[^0-9]', '', line)
        if cleaned_num and len(cleaned_num) >= 4 and len(cleaned_num) <= 10:
            numbers.append(cleaned_num)
        else:
            # 숫자가 아닌 줄은 고객명으로 인식
            name_cand = re.sub(r'[\r\n\t]+', '', line).strip()
            if name_cand and not name_cand.startswith("http"):
                customer_name = name_cand

    if not numbers:
        # 혹시 전체 텍스트에서 6~8자리 숫자들 추출 시도
        found_nums = re.findall(r'\b\d{6,8}\b', scanned_text)
        if found_nums:
            numbers = found_nums

    if not numbers:
        conn.close()
        return jsonify({"success": False, "message": "스캔 내용에서 상품 접수번호를 찾을 수 없습니다."}), 400

    # DB에 저장 / 업데이트
    saved_items = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with conn:
        for num in numbers:
            # 기존 등록 여부 확인
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
    code = data.get("code", "").strip()
    name = data.get("name", "").strip() or code
    zone = data.get("zone", "").strip() or "기본"

    if not code:
        return jsonify({"success": False, "message": "자리 코드를 입력해주세요."}), 400

    conn = database.get_connection()
    try:
        with conn:
            conn.execute("INSERT INTO locations (code, name, zone) VALUES (?, ?, ?)", (code, name, zone))
        conn.close()
        return jsonify({"success": True, "message": f"자리 '{code}' 추가 완료"})
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 400

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print(f"📦 [카에루몰 스마트 창고 로케이션 시스템 서버 시작]")
    print(f"🖥️ PC 접속 주소:     http://localhost:{port}")
    print(f"📱 스마트폰 접속 주소: http://{local_ip}:{port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
