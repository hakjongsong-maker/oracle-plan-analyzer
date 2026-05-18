@echo off
cd /d "%~dp0"
echo ====================================
echo  Oracle Plan Analyzer - EXE 빌드
echo ====================================

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller 설치 중...
    pip install pyinstaller
)

echo.
echo 빌드 시작...
pyinstaller oracle_plan_analyzer.spec --clean

if errorlevel 1 (
    echo.
    echo [오류] 빌드 실패
    pause
    exit /b 1
)

echo.
echo ====================================
echo  빌드 완료!
echo  결과: dist\OraclePlanAnalyzer.exe
echo ====================================
explorer dist
pause
