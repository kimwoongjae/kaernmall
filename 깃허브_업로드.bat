@echo off
chcp 65001 > nul
title 카에루몰 깃허브 자동 업로드 (Git Push)

echo ============================================================
echo      🚀 카에루몰 창고 시스템 - 깃허브 원클릭 자동 업로드
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/3] 변경된 파일 확인 중...
git status --short

echo.
set /p commit_msg="커밋 메시지를 입력하세요 (엔터 치면 자동 생성): "

if "%commit_msg%"=="" (
    set commit_msg=업데이트: %date% %time%
)

echo.
echo [2/3] 변경 파일 스테이징 및 커밋 생성 중... ("%commit_msg%")
git add .
git commit -m "%commit_msg%"

echo.
echo [3/3] 깃허브(GitHub) 서버로 업로드(Push) 중...
git push origin main

if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo  ✅ 깃허브 업로드가 성공적으로 완료되었습니다!
    echo  🌐 저장소: https://github.com/kimwoongjae/kaernmall
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo  ❌ 업로드 중 오류가 발생했습니다.
    echo ============================================================
)

echo.
pause
