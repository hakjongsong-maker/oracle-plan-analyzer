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

# SELECT 키워드 (앞에 공백 허용, 이미 힌트 블록이 있는 경우 포함)
_SELECT_HINT_RE = re.compile(
    r"(SELECT\s*)(/\*\+[^*]*\*/)?\s*",
    re.IGNORECASE,
)


def _inject_no_dynamic_sampling(sql: str) -> str:
    """
    SQL이 SELECT 로 시작할 때 첫 번째 SELECT 뒤에
    /*+ dynamic_sampling(0) */ 힌트를 추가한다.

    - ALTER SESSION 없이 Oracle Dynamic Sampling 을 SQL 힌트 레벨로 차단
    - 이미 힌트 블록이 있으면 기존 블록 안에 추가
    - SELECT 가 아닌 문장(WITH/INSERT/UPDATE/DELETE)은 그대로 반환
    """
    stripped = sql.lstrip()
    if not re.match(r"SELECT\b", stripped, re.IGNORECASE):
        return sql   # 힌트 추가 불가 → 원본 반환

    def _replace(m: re.Match) -> str:
        kw = m.group(1)          # "SELECT " (원본 케이스·공백 유지)
        existing = m.group(2)    # 기존 /*+ ... */ 또는 None

        if existing:
            # /*+ 기존 내용 */ → /*+ dynamic_sampling(0) 기존 내용 */
            new_hint = existing.replace("/*+", "/*+ dynamic_sampling(0)", 1)
            return kw + new_hint + " "
        else:
            return kw + "/*+ dynamic_sampling(0) */ "

    return _SELECT_HINT_RE.sub(_replace, sql, count=1)

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

    cursor = connection.cursor()
    try:
        # ── Dynamic Sampling 차단 (SQL 힌트 방식 — ALTER SESSION 불필요) ──────
        # EXPLAIN PLAN 실행 중 Oracle 옵티마이저가 테이블 통계 부족 시
        # SELECT ... SAMPLE(...) 을 내부 실행(Dynamic Sampling)하는 현상 차단.
        # ALTER SESSION 대신 /*+ dynamic_sampling(0) */ 힌트를 SQL에 직접 삽입.
        # SELECT 이외의 문장(WITH/INSERT/UPDATE/DELETE)은 힌트 미삽입.
        plan_sql = _inject_no_dynamic_sampling(converted_sql)

        # ── EXPLAIN PLAN 직접 실행 ───────────────────────────────────────────
        # EXPLAIN PLAN 은 SELECT 를 실행하지 않고 실행 계획만 PLAN_TABLE 에 저장.
        # use_bind_vars=True  → plan_sql 의 :v1 에 None(NULL) 바인드
        # use_bind_vars=False → 원본 SQL(리터럴), 바인드 변수 없음
        explain_stmt = f"EXPLAIN PLAN SET STATEMENT_ID = '{stmt_id}' FOR {plan_sql}"

        if use_bind_vars and bind_map:
            bind_params = {k.lstrip(':'): None for k in bind_map.keys()}
            cursor.execute(explain_stmt, bind_params)
        else:
            cursor.execute(explain_stmt)

        # ── DBMS_XPLAN.DISPLAY 로 실행계획 조회 ──────────────────────────────
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

    except Exception as e:
        result.error = str(e)
        result.success = False

    finally:
        try:
            cursor.close()
        except Exception:
            pass

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
