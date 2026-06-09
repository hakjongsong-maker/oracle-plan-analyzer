"""Execute EXPLAIN PLAN via DBMS_XPLAN and parse results."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class PlanStep:
    id: int = 0
    operation: str = ""
    options: str = ""
    object_name: str = ""
    rows: str = ""
    bytes: str = ""
    cost: str = ""
    time: str = ""


@dataclass
class PlanResult:
    db_id: int = 0
    db_label: str = ""
    plan_hash: Optional[str] = None
    plan_text: str = ""
    plan_steps: List[PlanStep] = field(default_factory=list)
    error: Optional[str] = None
    success: bool = False
    converted_sql: str = ""          # 바인드 변수로 치환된 SQL
    bind_map: Dict[str, str] = field(default_factory=dict)  # {:v1: "'값'", ...}


_HASH_RE = re.compile(r"Plan hash value:\s*(\d+)", re.IGNORECASE)

# DATE/TIMESTAMP/INTERVAL 리터럴은 치환 제외, 나머지 문자열 상수만 치환
# 예) 'SCOTT' → :v1  /  DATE '2024-01-01' → 유지
_LITERAL_RE = re.compile(
    r"(DATE|TIMESTAMP|INTERVAL)\s*'(?:[^']|'')*'"   # 날짜/시간 리터럴 — 유지
    r"|"
    r"'(?:[^']|'')*'",                               # 일반 문자열 리터럴 — 치환
    re.IGNORECASE,
)


def bind_string_literals(sql: str) -> tuple[str, dict]:
    """
    SQL 내 문자열 상수('값')를 바인드 변수(:v1, :v2, ...)로 치환.
    DATE/TIMESTAMP/INTERVAL 리터럴은 그대로 유지.
    반환: (치환된 SQL, {':v1': "'원래값'", ...})
    """
    binds: dict = {}
    counter = [0]

    def _replace(m: re.Match) -> str:
        # DATE/TIMESTAMP/INTERVAL 접두어가 있으면 치환하지 않음
        if m.group(1):
            return m.group(0)
        counter[0] += 1
        var = f":v{counter[0]}"
        binds[var] = m.group(0)
        return var

    converted = _LITERAL_RE.sub(_replace, sql)
    return converted, binds

# Row pattern: |  id  | Operation  | Name  | Rows | Bytes | Cost |  Time  |
_ROW_RE = re.compile(
    r"\|\s*\*?\s*(\d+)\s*\|"          # id
    r"\s*([\w\s]+?)\s*\|"             # operation
    r"\s*([\w$#\s]*?)\s*\|"           # name
    r"\s*([\d KMG]*?)\s*\|"           # rows
    r"\s*([\d KMG]*?)\s*\|"           # bytes
    r"\s*([\d]+(?:\s*\(\d+\))?)\s*\|" # cost
)


def get_plan_hash(plan_text: str) -> Optional[str]:
    m = _HASH_RE.search(plan_text)
    return m.group(1) if m else None


def parse_plan_steps(plan_text: str) -> List[PlanStep]:
    steps: List[PlanStep] = []
    for line in plan_text.splitlines():
        m = _ROW_RE.match(line.strip())
        if m:
            op_full = m.group(2).strip()
            # Split operation and options (e.g. "TABLE ACCESS" + "FULL")
            parts = op_full.rsplit(None, 1)
            operation = parts[0] if len(parts) > 1 else op_full
            # operation / options will be parsed later from the display string
            steps.append(PlanStep(
                id=int(m.group(1)),
                operation=m.group(2).strip(),
                object_name=m.group(3).strip(),
                rows=m.group(4).strip(),
                bytes=m.group(5).strip(),
                cost=m.group(6).strip(),
            ))
    return steps


def explain_plan(connection, sql: str, db_id: int, db_label: str,
                 use_bind_vars: bool = True) -> PlanResult:
    result = PlanResult(db_id=db_id, db_label=db_label)

    # DB별 고정 STATEMENT_ID (OPA1 ~ OPA6) — PLAN_TABLE에서 직접 조회 가능
    stmt_id = f"OPA{db_id + 1}"

    sql = sql.strip().rstrip(";")
    if not sql:
        result.error = "SQL이 비어 있습니다."
        return result

    # 체크박스 ON: 문자열 상수 → 바인드 변수 치환 / OFF: 원본 SQL 그대로 사용
    if use_bind_vars:
        converted_sql, bind_map = bind_string_literals(sql)
    else:
        converted_sql, bind_map = sql, {}
    result.converted_sql = converted_sql
    result.bind_map = bind_map

    try:
        cursor = connection.cursor()

        # EXPLAIN PLAN 을 PL/SQL EXECUTE IMMEDIATE 로 실행
        # ─ 이유: cursor.execute()로 직접 실행하면 converted_sql 안의
        #   :v1 등 바인드 변수를 oracledb 가 파라미터로 오해해
        #   SQL 이 실제 실행되는 문제 방지
        # ─ converted_sql 내부 작은따옴표를 '' 로 이스케이프
        sql_escaped = converted_sql.replace("'", "''")
        plsql = (
            f"BEGIN "
            f"  EXECUTE IMMEDIATE "
            f"    'EXPLAIN PLAN SET STATEMENT_ID = ''{stmt_id}'' "
            f"     FOR {sql_escaped}'; "
            f"END;"
        )
        cursor.execute(plsql)

        # DBMS_XPLAN.DISPLAY 로 실행계획 조회 (stmt_id 명시해 해당 플랜만 조회)
        cursor.execute(
            "SELECT PLAN_TABLE_OUTPUT "
            "FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', :sid, 'serial'))",
            sid=stmt_id,
        )
        rows = cursor.fetchall()
        plan_text = "\n".join(r[0] for r in rows)

        result.plan_text = plan_text
        result.plan_hash = get_plan_hash(plan_text)
        result.plan_steps = parse_plan_steps(plan_text)
        result.success = True

        cursor.close()
    except Exception as e:
        result.error = str(e)
        result.success = False

    return result


def extract_operations(plan_text: str) -> Dict[str, List[str]]:
    """Extract access methods and join methods from a plan text."""
    access = []
    joins = []
    for line in plan_text.splitlines():
        upper = line.upper()
        if "TABLE ACCESS FULL" in upper:
            m = re.search(r"TABLE ACCESS FULL\s*\|\s*(\w+)", line, re.IGNORECASE)
            if m:
                access.append(f"FULL SCAN: {m.group(1)}")
        elif "INDEX RANGE SCAN" in upper or "INDEX UNIQUE SCAN" in upper:
            m = re.search(r"INDEX (?:RANGE|UNIQUE) SCAN\s*\|\s*(\w+)", line, re.IGNORECASE)
            scan_type = "RANGE SCAN" if "RANGE" in upper else "UNIQUE SCAN"
            if m:
                access.append(f"INDEX {scan_type}: {m.group(1)}")
        if "NESTED LOOPS" in upper:
            joins.append("NESTED LOOPS")
        elif "HASH JOIN" in upper:
            joins.append("HASH JOIN")
        elif "SORT MERGE JOIN" in upper or "MERGE JOIN" in upper:
            joins.append("SORT MERGE JOIN")
    return {"access": access, "joins": list(set(joins))}
