"""Oracle DB connection manager — up to 6 connections."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional, Dict

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
            raise ConnectionError("oracledb 패키지가 설치되지 않았습니다.\npip install oracledb 를 실행하세요.")

        cfg = self._configs.get(db_id)
        if not cfg:
            raise ConnectionError("DB 설정이 없습니다.")
        if not cfg.tns_alias:
            raise ConnectionError("TNS Alias를 선택하세요.")
        if not cfg.username:
            raise ConnectionError("사용자명을 입력하세요.")

        tns_dir = os.path.dirname(cfg.tns_file) if cfg.tns_file else None

        try:
            conn_kwargs = dict(
                user=cfg.username,
                password=cfg.password,
                dsn=cfg.tns_alias,
            )
            if tns_dir:
                conn_kwargs["config_dir"] = tns_dir

            conn = oracledb.connect(**conn_kwargs)
            self._connections[db_id] = conn
        except Exception as e:
            raise ConnectionError(str(e)) from e

    def disconnect(self, db_id: int):
        conn = self._connections.pop(db_id, None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass

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
