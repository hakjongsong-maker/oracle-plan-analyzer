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
echo [1/2] PyInstaller 빌드 시작...
pyinstaller oracle_plan_analyzer.spec --clean

if errorlevel 1 (
    echo.
    echo [오류] 빌드 실패
    pause
    exit /b 1
)

echo.
echo [2/2] 10MB 분할 압축 생성 중...
python split_archive.py

if errorlevel 1 (
    echo.
    echo [오류] 분할 압축 실패
    pause
    exit /b 1
)

echo.
echo ====================================
echo  모든 작업 완료!
echo  - 단독 실행: dist\OraclePlanAnalyzer.exe
echo  - 분할 배포: dist\release\
echo ====================================
explorer dist\release
pause
