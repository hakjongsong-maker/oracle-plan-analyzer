"""
빌드된 exe를 암호화 zip 압축 후 분할합니다.
생성물: dist/release/OraclePlanAnalyzer_part01.zip ...
         dist/release/combine.bat  (분할 파일 재조합용)
         dist/release/README.txt
"""
import os
import sys
import math
import hashlib
import shutil
from pathlib import Path

import pyzipper

# Windows 콘솔 UTF-8 출력 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 설정 ──────────────────────────────────────────────────────────────────────
EXE_NAME     = "OraclePlanAnalyzer.exe"
TXT_NAME     = "OraclePlanAnalyzer.txt"   # 압축 내부 파일명 (.exe → .txt)
ZIP_PASSWORD = b"0000"                     # 압축 파일 암호
CHUNK_MB     = 5
CHUNK_BYTES  = CHUNK_MB * 1024 * 1024
BASE_DIR     = Path(__file__).parent
DIST_DIR     = BASE_DIR / "dist"
RELEASE_DIR  = DIST_DIR / "release"
EXE_PATH     = DIST_DIR / EXE_NAME


def md5_of_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_zip(exe_path: Path, zip_path: Path):
    print(f"  압축 중: {exe_path.name} → {TXT_NAME} (확장자 .txt 변환)")
    print(f"           → {zip_path.name}  (암호: {ZIP_PASSWORD.decode()})")
    with pyzipper.AESZipFile(
        zip_path, "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(ZIP_PASSWORD)
        # exe 파일을 .txt 이름으로 저장
        zf.write(exe_path, TXT_NAME)
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  압축 완료: {size_mb:.1f} MB")
    return zip_path


def split_file(src: Path, out_dir: Path, chunk_bytes: int) -> list[Path]:
    total   = src.stat().st_size
    n_parts = math.ceil(total / chunk_bytes)
    parts   = []

    print(f"\n  분할: {src.name} ({total/1024/1024:.1f} MB) → {n_parts}개 파트")

    with open(src, "rb") as f:
        for i in range(n_parts):
            data      = f.read(chunk_bytes)
            part_name = f"{src.stem}_part{i+1:02d}.zip"
            part_path = out_dir / part_name
            with open(part_path, "wb") as pf:
                pf.write(data)
            print(f"    {part_name}  ({len(data)/1024/1024:.1f} MB)")
            parts.append(part_path)

    return parts


def make_combine_bat(parts: list[Path], out_dir: Path, zip_name: str):
    part_names = " + ".join(p.name for p in parts)
    script = (
        "@echo off\n"
        "echo =============================================\n"
        "echo  OraclePlanAnalyzer 분할 파일 재조합\n"
        "echo =============================================\n"
        "echo.\n"
        "echo [1/3] 분할 파일 재조합 중...\n"
        f"copy /b {part_names} {zip_name}\n"
        "if errorlevel 1 (\n"
        "    echo [오류] 파일 재조합 실패\n"
        "    pause\n"
        "    exit /b 1\n"
        ")\n"
        "echo.\n"
        f"echo [완료] {zip_name} 생성됨\n"
        "echo.\n"
        f"echo [2/3] {zip_name} 압축을 해제하세요.\n"
        f"echo       암호: {ZIP_PASSWORD.decode()}\n"
        "echo.\n"
        f"echo [3/3] 압축 해제 후 {TXT_NAME} 파일의 확장자를 .txt -> .exe 로 변경하세요.\n"
        f"echo       변경 방법: {TXT_NAME} 파일 선택 -> F2 -> OraclePlanAnalyzer.exe 로 변경\n"
        "echo.\n"
        "pause\n"
    )
    bat_path = out_dir / "combine.bat"
    bat_path.write_text(script, encoding="utf-8")
    print(f"\n  재조합 스크립트: {bat_path.name}")


def make_readme(parts: list[Path], zip_name: str, exe_md5: str, out_dir: Path):
    lines = [
        "OraclePlanAnalyzer 배포 패키지",
        "=" * 40,
        "",
        f"원본 파일  : {EXE_NAME}",
        f"MD5 (exe)  : {exe_md5}",
        f"분할 크기  : {CHUNK_MB} MB",
        f"분할 개수  : {len(parts)}개",
        "",
        f"압축 암호   : {ZIP_PASSWORD.decode()}",
        f"내부 파일명 : {TXT_NAME}  (압축 해제 후 .exe 로 변경 필요)",
        "",
        "[ 사용 방법 ]",
        "1. 이 폴더의 모든 파일을 같은 경로에 복사합니다.",
        "2. combine.bat 을 실행하면 zip 파일이 생성됩니다.",
        f"3. {zip_name} 압축 해제 시 암호 '{ZIP_PASSWORD.decode()}' 를 입력합니다.",
        f"4. 압축 해제된 {TXT_NAME} 파일명을 {EXE_NAME} 으로 변경합니다.",
        f"   (파일 선택 후 F2 키 -> 확장자 .txt 를 .exe 로 수정)",
        f"5. {EXE_NAME} 를 실행합니다.",
        "   (Python / Oracle Instant Client 설치 불필요)",
        "",
        "[ 분할 파일 목록 ]",
    ]
    for p in parts:
        lines.append(f"  {p.name}  ({p.stat().st_size/1024/1024:.1f} MB)")
    lines += ["", "[ 주의 사항 ]",
              "- oracledb Thin 모드로 동작하므로 Oracle Client 불필요",
              "- tnsnames.ora 파일 경로만 미리 준비하세요.", ""]

    (out_dir / "README.txt").write_text("\n".join(lines), encoding="utf-8")
    print("  README.txt 생성됨")


def main():
    print("=" * 50)
    print(" Oracle Plan Analyzer - 분할 압축 생성")
    print("=" * 50)

    if not EXE_PATH.exists():
        print(f"\n[오류] 실행 파일이 없습니다: {EXE_PATH}")
        print("먼저 build_exe.bat 으로 빌드하세요.")
        sys.exit(1)

    # 릴리스 폴더 초기화
    if RELEASE_DIR.exists():
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True)

    # exe MD5 계산
    exe_md5 = md5_of_file(EXE_PATH)
    print(f"\n  {EXE_NAME}  MD5: {exe_md5}")

    # zip 압축
    zip_name = EXE_NAME.replace(".exe", ".zip")
    tmp_zip  = RELEASE_DIR / zip_name
    make_zip(EXE_PATH, tmp_zip)

    # 10MB 분할
    parts = split_file(tmp_zip, RELEASE_DIR, CHUNK_BYTES)

    # 원본 zip 삭제 (분할 파트만 남김)
    tmp_zip.unlink()

    # combine.bat 생성
    make_combine_bat(parts, RELEASE_DIR, zip_name)

    # README 생성
    make_readme(parts, zip_name, exe_md5, RELEASE_DIR)

    # 결과 요약
    total_release = sum(p.stat().st_size for p in RELEASE_DIR.iterdir())
    print("\n" + "=" * 50)
    print(f" 완료!  dist\\release\\  ({total_release/1024/1024:.1f} MB 총)")
    print("=" * 50)
    for f in sorted(RELEASE_DIR.iterdir()):
        print(f"  {f.name}")

    # 메일 발송
    print("\n" + "=" * 50)
    print(" 분할 파일 메일 발송 시작")
    print("=" * 50)
    from mail_sender import send_parts
    send_parts(parts)


if __name__ == "__main__":
    main()
