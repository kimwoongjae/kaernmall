@echo off
chcp 65001 > nul
title 카에루몰 스마트 창고 로케이션 서버
cd /d "%~dp0"
python server_launcher.py
pause
