"""Oracle DB connection manager — up to 6 connections."""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional, Dict

from app_logger import log

try:
    import oracledb
    ORACLEDB_AVAILABLE = True
except ImportError:
    ORACLEDB_AVAILABLE = False


@dataclass
class DBConfig:
    label: str = ""
    tns_file: str = ""
    tns_alias: str = ""
    username: str = ""
    password: str = ""


class ConnectionError(Exception):
    pass


class DBManager:
    MAX_DB = 6

    def __init__(self):
        self._configs: Dict[int, DBConfig] = {}
        self._connections: Dict[int, object] = {}

    def set_config(self, db_id: int, config: DBConfig):
        if 0 <= db_id < self.MAX_DB:
            self._configs[db_id] = config

    def get_config(self, db_id: int) -> Optional[DBConfig]:
        return self._configs.get(db_id)

    def connect(self, db_id: int) -> None:
        if not ORACLEDB_AVAILABLE:
            raise ConnectionError(
                "oracledb 패키지가 설치되지 않았습니다.\n"
                "pip install oracledb 를 실행하세요."
            )

        cfg = self._configs.get(db_id)
        if not cfg:
            raise ConnectionError("DB 설정이 없습니다.")

        # ── 입력값 검증 ───────────────────────────────────────────────────────
        if not cfg.tns_alias.strip():
            raise ConnectionError("TNS Alias를 선택하세요.")
        if not cfg.username.strip():
            raise ConnectionError("사용자명을 입력하세요.")

        # ── tnsnames.ora 경로 검증 ────────────────────────────────────────────
        # DPY-4018 방지: config_dir 없이 alias만 넘기면 EZConnect 파싱 시도 → 오류
        tns_file = cfg.tns_file.strip()
        if not tns_file:
            raise ConnectionError(
                "tnsnames.ora 파일이 설정되지 않았습니다.\n"
                "상단의 [tnsnames.ora (공통)] 에서 파일을 먼저 선택하세요."
            )
        if not os.path.isfile(tns_file):
            raise ConnectionError(
                f"tnsnames.ora 파일을 찾을 수 없습니다.\n경로: {tns_file}"
            )

        config_dir = os.path.dirname(os.path.abspath(tns_file))

        log.info(
            "[DB%d] 접속 시도 — alias=%s, user=%s, config_dir=%s",
            db_id + 1, cfg.tns_alias, cfg.username, config_dir,
        )

        try:
            conn = oracledb.connect(
                user=cfg.username,
                password=cfg.password,
                dsn=cfg.tns_alias.strip(),
                config_dir=config_dir,
            )
            self._connections[db_id] = conn
            log.info("[DB%d] 접속 성공", db_id + 1)

        except Exception as e:
            log.error("[DB%d] 접속 실패: %s", db_id + 1, e)
            raise ConnectionError(str(e)) from e

    def disconnect(self, db_id: int):
        conn = self._connections.pop(db_id, None)
        if conn:
            try:
                conn.close()
                log.info("[DB%d] 접속 종료", db_id + 1)
            except Exception as e:
                log.warning("[DB%d] 접속 종료 중 오류: %s", db_id + 1, e)

    def is_connected(self, db_id: int) -> bool:
        conn = self._connections.get(db_id)
        if conn is None:
            return False
        try:
            conn.ping()
            return True
        except Exception:
            self._connections.pop(db_id, None)
            return False

    def get_connection(self, db_id: int):
        return self._connections.get(db_id)

    def connected_ids(self):
        return [i for i in range(self.MAX_DB) if self.is_connected(i)]
