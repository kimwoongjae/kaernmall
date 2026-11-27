import os, sys, socket, webbrowser, time, subprocess

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 5000
    url = f"http://localhost:{port}"
    mobile_url = f"http://{local_ip}:{port}"

    print("=" * 65)
    print("   📦 카에루몰 스마트 창고 로케이션 & QR 관리 서버 시작")
    print("=" * 65)
    print(f"🖥️  관리자 PC 접속 주소:     {url}")
    print(f"📱 스마트폰 현장 접속 주소: {mobile_url}")
    print("=" * 65)
    print("💡 스마트폰과 PC가 같은 Wi-Fi에 연결되어 있으면")
    print(f"   스마트폰 브라우저에서 '{mobile_url}' 에 접속하시면 됩니다!")
    print("=" * 65)
    print("서버를 종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.\n")

    # 브라우저 자동 오픈
    try:
        webbrowser.open(url)
    except Exception:
        pass

    # Flask 앱 실행
    from app import app
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
