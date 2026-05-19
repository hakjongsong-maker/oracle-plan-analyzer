"""
애플리케이션 로거 — 실행파일(또는 스크립트) 폴더에 로그 파일 생성.
로그 파일: oracle_plan_analyzer.log  (최대 5MB × 3세대 롤링)
"""
from __future__ import annotations
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOG_FILENAME = "oracle_plan_analyzer.log"
_MAX_BYTES    = 5 * 1024 * 1024   # 5 MB
_BACKUP_COUNT = 3


def _get_log_dir() -> str:
    """exe 실행 시 → exe 폴더 / 스크립트 실행 시 → 스크립트 폴더."""
    if getattr(sys, "frozen", False):          # PyInstaller exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def setup_logger() -> logging.Logger:
    log_path = os.path.join(_get_log_dir(), _LOG_FILENAME)

    logger = logging.getLogger("OraclePlanAnalyzer")
    if logger.handlers:          # 이미 초기화된 경우 재사용
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(module)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── 파일 핸들러 (롤링) ────────────────────────────────────────────────────
    try:
        fh = RotatingFileHandler(
            log_path, maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT, encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError as e:
        # 파일 쓰기 실패 시 콘솔만 사용
        print(f"[경고] 로그 파일 생성 실패: {e}")

    # ── 콘솔 핸들러 (WARNING 이상만) ─────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("=" * 60)
    logger.info("Oracle Plan Analyzer 시작")
    logger.info("로그 파일: %s", log_path)
    logger.info("=" * 60)
    return logger


# 전역 싱글톤
log = setup_logger()
