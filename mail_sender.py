"""
분할 압축 파일을 개별 메일로 발송합니다.
발송 방법: Outlook 자동화(기본) → SMTP(fallback)
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

    if "receiver_email" not in cfg:
        print("[오류] mail_config.json 에 'receiver_email' 항목이 없습니다.")
        sys.exit(1)

    return cfg


# ── 메일 본문 생성 (공통) ──────────────────────────────────────────────────────
def _make_body(part_path: Path, part_num: int, total_parts: int) -> str:
    size_mb = part_path.stat().st_size / 1024 / 1024
    return (
        f"OraclePlanAnalyzer 분할 배포 파일입니다.\n\n"
        f"  파일명  : {part_path.name}\n"
        f"  크기    : {size_mb:.1f} MB\n"
        f"  파트    : {part_num} / {total_parts}\n\n"
        f"-----------------------------------------\n"
        f"[ 전체 파일 수신 후 사용 방법 ]\n"
        f"1. 모든 파트 파일 ({total_parts}개) + combine.bat 을 같은 폴더에 저장\n"
        f"2. combine.bat 실행 -> OraclePlanAnalyzer.zip 생성\n"
        f"3. zip 압축 해제 -> OraclePlanAnalyzer.exe 실행\n"
        f"   (Python / Oracle Instant Client 설치 불필요)\n"
        f"-----------------------------------------\n"
    )


def _make_subject(part_path: Path, part_num: int, total_parts: int) -> str:
    return f"[OraclePlanAnalyzer] 배포 파일 {part_num}/{total_parts} - {part_path.name}"


# ── ① Outlook 자동화 발송 ──────────────────────────────────────────────────────
def _send_one_outlook(outlook_app, part_path: Path, part_num: int,
                      total_parts: int, receiver: str) -> None:
    """Outlook COM 객체로 메일 1통 발송."""
    mail = outlook_app.CreateItem(0)          # 0 = olMailItem
    mail.To      = receiver
    mail.Subject = _make_subject(part_path, part_num, total_parts)
    mail.Body    = _make_body(part_path, part_num, total_parts)
    mail.Attachments.Add(str(part_path.resolve()))
    mail.Send()


def send_parts_outlook(part_files: list[Path], cfg: dict,
                       delay_sec: int = 2) -> bool:
    """Outlook 자동화로 파트 파일 개별 발송."""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        # 간단한 동작 확인
        _ = outlook.Version
    except Exception as e:
        print(f"  [Outlook] 초기화 실패: {e}")
        return False

    total         = len(part_files)
    receiver      = cfg["receiver_email"]
    success_count = 0

    for i, part_path in enumerate(part_files, start=1):
        try:
            _send_one_outlook(outlook, part_path, i, total, receiver)
            size_mb = part_path.stat().st_size / 1024 / 1024
            print(f"  [{i}/{total}] 발송 완료: {part_path.name} ({size_mb:.1f} MB)")
            success_count += 1
            if i < total:
                time.sleep(delay_sec)
        except Exception as e:
            print(f"  [{i}/{total}] 발송 실패: {part_path.name} - {e}")

    print(f"\n  결과: {success_count}/{total}개 발송 성공")
    return success_count == total


# ── ② SMTP 발송 (fallback) ────────────────────────────────────────────────────
def _build_smtp_message(cfg: dict, part_path: Path,
                        part_num: int, total_parts: int) -> MIMEMultipart:
    msg            = MIMEMultipart()
    msg["From"]    = cfg.get("sender_email", "")
    msg["To"]      = cfg["receiver_email"]
    msg["Subject"] = _make_subject(part_path, part_num, total_parts)
    msg.attach(MIMEText(_make_body(part_path, part_num, total_parts), "plain", "utf-8"))

    with open(part_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition",
                    f'attachment; filename="{part_path.name}"')
    msg.attach(part)
    return msg


def _connect_smtp(cfg: dict):
    """STARTTLS(587) → SSL(465) 순서로 연결 시도."""
    attempts = [
        ("STARTTLS", cfg.get("smtp_server", "smtp.gmail.com"), cfg.get("smtp_port", 587)),
        ("SSL",      cfg.get("smtp_server", "smtp.gmail.com"), 465),
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
            server.login(cfg.get("sender_email", ""), cfg.get("app_password", ""))
            print("로그인 성공")
            return server
        except smtplib.SMTPAuthenticationError:
            print("실패\n[오류] Gmail 인증 실패 — app_password 를 확인하세요.")
            return None
        except Exception as e:
            print(f"실패 ({e})")
    print("\n[오류] SMTP 연결 실패 — 포트 587, 465 모두 차단됨")
    return None


def send_parts_smtp(part_files: list[Path], cfg: dict,
                    delay_sec: int = 3) -> bool:
    """SMTP로 파트 파일 개별 발송."""
    server = _connect_smtp(cfg)
    if server is None:
        return False

    total         = len(part_files)
    success_count = 0

    for i, part_path in enumerate(part_files, start=1):
        try:
            msg = _build_smtp_message(cfg, part_path, i, total)
            server.sendmail(cfg["sender_email"], cfg["receiver_email"], msg.as_string())
            size_mb = part_path.stat().st_size / 1024 / 1024
            print(f"  [{i}/{total}] 발송 완료: {part_path.name} ({size_mb:.1f} MB)")
            success_count += 1
            if i < total:
                time.sleep(delay_sec)
        except Exception as e:
            print(f"  [{i}/{total}] 발송 실패: {part_path.name} - {e}")

    server.quit()
    print(f"\n  결과: {success_count}/{total}개 발송 성공")
    return success_count == total


# ── 공개 진입점 ───────────────────────────────────────────────────────────────
def send_parts(part_files: list[Path], delay_sec: int = 2) -> bool:
    """
    Outlook 자동화 시도 → 실패 시 SMTP 로 fallback.
    """
    cfg   = load_config()
    total = len(part_files)

    print(f"\n  수신자   : {cfg['receiver_email']}")
    print(f"  파일 수  : {total}개\n")

    # ── Outlook 시도 ──────────────────────────────────────────────────────────
    print("  [방법 1] Outlook 자동화 시도...")
    ok = send_parts_outlook(part_files, cfg, delay_sec)
    if ok:
        return True

    # ── SMTP fallback ─────────────────────────────────────────────────────────
    print("\n  [방법 2] SMTP 발송으로 전환...")
    sender = cfg.get("sender_email", "")
    pwd    = cfg.get("app_password", "")
    if not sender or not pwd or "앱비밀번호" in pwd:
        print("  [SMTP 건너뜀] mail_config.json 의 sender_email / app_password 미설정")
        return False

    return send_parts_smtp(part_files, cfg, delay_sec)


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
