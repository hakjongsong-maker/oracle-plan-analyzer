"""
분할 압축 파일을 SMTP 로 개별 메일 발송합니다.
설정: mail_config.json
"""
import json
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

# Windows 콘솔 UTF-8 출력 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CONFIG_PATH = Path(__file__).parent / "mail_config.json"


# ── 설정 로드 ─────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[오류] 설정 파일이 없습니다: {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

    required = ["smtp_server", "smtp_port", "sender_email", "app_password", "receiver_email"]
    for key in required:
        if key not in cfg:
            print(f"[오류] mail_config.json 에 '{key}' 항목이 없습니다.")
            sys.exit(1)

    if "앱비밀번호" in cfg["app_password"] or not cfg["app_password"].strip():
        print("[오류] mail_config.json 의 app_password 를 실제 Gmail 앱 비밀번호로 변경하세요.")
        print("  설정 방법: https://myaccount.google.com/apppasswords")
        sys.exit(1)

    return cfg


# ── 메일 메시지 생성 ──────────────────────────────────────────────────────────
def _build_message(cfg: dict, part_path: Path, part_num: int, total_parts: int) -> MIMEMultipart:
    msg            = MIMEMultipart()
    msg["From"]    = cfg["sender_email"]
    msg["To"]      = cfg["receiver_email"]
    msg["Subject"] = (
        f"[OraclePlanAnalyzer] 배포 파일 {part_num}/{total_parts} - {part_path.name}"
    )

    size_mb = part_path.stat().st_size / 1024 / 1024
    body = (
        f"OraclePlanAnalyzer 분할 배포 파일입니다.\n\n"
        f"  파일명  : {part_path.name}\n"
        f"  크기    : {size_mb:.1f} MB\n"
        f"  파트    : {part_num} / {total_parts}\n\n"
        f"-----------------------------------------\n"
        f"[ 전체 파일 수신 후 사용 방법 ]\n"
        f"1. 모든 파트 파일 ({total_parts}개) + combine.bat 을 같은 폴더에 저장\n"
        f"2. combine.bat 실행 -> OraclePlanAnalyzer.zip 생성\n"
        f"3. zip 압축 해제 시 암호 '0000' 입력\n"
        f"4. OraclePlanAnalyzer.exe 실행\n"
        f"   (Python / Oracle Instant Client 설치 불필요)\n"
        f"-----------------------------------------\n"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(part_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{part_path.name}"')
    msg.attach(part)
    return msg


# ── SMTP 연결 (STARTTLS → SSL 자동 전환) ─────────────────────────────────────
def _connect_smtp(cfg: dict):
    """
    STARTTLS(587) → SSL(465) 순서로 연결을 시도합니다.
    성공 시 로그인된 서버 객체 반환, 실패 시 None 반환.
    """
    attempts = [
        ("STARTTLS", cfg["smtp_server"], cfg.get("smtp_port", 587)),
        ("SSL",      cfg["smtp_server"], 465),
    ]

    for method, host, port in attempts:
        try:
            print(f"  접속 시도: {host}:{port} ({method}) ...", end=" ", flush=True)
            if method == "STARTTLS":
                server = smtplib.SMTP(host, port, timeout=15)
                server.ehlo()
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(host, port, timeout=15)
                server.ehlo()

            server.login(cfg["sender_email"], cfg["app_password"])
            print("로그인 성공")
            return server

        except smtplib.SMTPAuthenticationError:
            print("실패")
            print("\n[오류] Gmail 인증 실패 — 앱 비밀번호를 확인하세요.")
            print("  설정: https://myaccount.google.com/apppasswords")
            return None

        except Exception as e:
            print(f"실패 ({e})")
            continue

    print("\n[오류] SMTP 연결 실패 — 포트 587, 465 모두 차단되어 있습니다.")
    print("  네트워크 방화벽 또는 VPN 설정을 확인하세요.")
    return None


# ── 공개 진입점 ───────────────────────────────────────────────────────────────
def send_parts(part_files: list[Path], delay_sec: int = 3) -> bool:
    """각 파트 파일을 개별 SMTP 메일로 순차 발송."""
    cfg   = load_config()
    total = len(part_files)

    print(f"\n  수신자   : {cfg['receiver_email']}")
    print(f"  발신자   : {cfg['sender_email']}")
    print(f"  SMTP     : {cfg['smtp_server']}:{cfg['smtp_port']}")
    print(f"  발송 건수: {total}개 메일\n")

    server = _connect_smtp(cfg)
    if server is None:
        return False

    success_count = 0
    for i, part_path in enumerate(part_files, start=1):
        try:
            msg = _build_message(cfg, part_path, i, total)
            server.sendmail(cfg["sender_email"], cfg["receiver_email"], msg.as_string())
            size_mb = part_path.stat().st_size / 1024 / 1024
            print(f"  [{i}/{total}] 발송 완료: {part_path.name} ({size_mb:.1f} MB)")
            success_count += 1
            if i < total:
                time.sleep(delay_sec)   # Gmail 연속 전송 제한 방지
        except Exception as e:
            print(f"  [{i}/{total}] 발송 실패: {part_path.name} - {e}")

    server.quit()
    print(f"\n  결과: {success_count}/{total}개 발송 성공")
    return success_count == total


# ── 단독 실행 ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    release_dir = Path(__file__).parent / "dist" / "release"
    parts       = sorted(release_dir.glob("*_part*.zip"))

    if not parts:
        print(f"[오류] 분할 파일이 없습니다: {release_dir}")
        print("먼저 build_exe.bat 또는 split_archive.py 를 실행하세요.")
        sys.exit(1)

    print("=" * 50)
    print(" Oracle Plan Analyzer - 분할 파일 메일 발송")
    print("=" * 50)
    for p in parts:
        print(f"  {p.name}  ({p.stat().st_size/1024/1024:.1f} MB)")

    ok = send_parts(parts)
    sys.exit(0 if ok else 1)
