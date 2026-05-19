@echo off
chcp 65001 > nul
echo =============================================
echo  OraclePlanAnalyzer 분할 파일 압축 해제
echo =============================================
echo.
echo [안내] 이 파일들은 WinZip 분할 ZIP 형식입니다.
echo        (.z01, .z02, ... , .zip) 모두 같은 폴더에 있어야 합니다.
echo.

:: 7-Zip 자동 탐색
set SEVENZIP=""
if exist "C:\Program Files\7-Zip\7z.exe"   set SEVENZIP="C:\Program Files\7-Zip\7z.exe"
if exist "C:\Program Files (x86)\7-Zip\7z.exe" set SEVENZIP="C:\Program Files (x86)\7-Zip\7z.exe"

if %SEVENZIP%=="" goto manual

:: 7-Zip 자동 압축 해제
echo [1/2] 7-Zip 으로 압축 해제 중...
%SEVENZIP% x "OraclePlanAnalyzer.zip" -p0000 -y
if errorlevel 1 (
    echo [오류] 압축 해제 실패
    pause
    exit /b 1
)
echo.
echo [2/2] OraclePlanAnalyzer.txt 파일 확장자를 .exe 로 변경하세요.
echo       방법: OraclePlanAnalyzer.txt 선택 후 F2 -> OraclePlanAnalyzer.exe 로 변경
echo.
pause
exit /b 0

:manual
echo [수동 안내] 7-Zip 이 설치되어 있지 않습니다.
echo.
echo  1. 7-Zip(https://www.7-zip.org) 또는 WinRAR 을 설치합니다.
echo  2. 'OraclePlanAnalyzer.zip' 파일을 우클릭 -> '여기에 압축 풀기'
echo     (암호: 0000)
echo  3. 압축 해제된 'OraclePlanAnalyzer.txt' 파일명을 'OraclePlanAnalyzer.exe' 으로 변경합니다.
echo.
pause
