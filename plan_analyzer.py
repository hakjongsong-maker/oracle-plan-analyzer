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


_HASH_RE = re.compile(r"Plan hash value:\s*(\d+)", re.IGNORECASE)

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


def explain_plan(connection, sql: str, db_id: int, db_label: str) -> PlanResult:
    result = PlanResult(db_id=db_id, db_label=db_label)

    # DB별 고정 STATEMENT_ID (OPA1 ~ OPA6) — PLAN_TABLE에서 직접 조회 가능
    stmt_id = f"OPA{db_id + 1}"

    sql = sql.strip().rstrip(";")
    if not sql:
        result.error = "SQL이 비어 있습니다."
        return result

    try:
        cursor = connection.cursor()

        # EXPLAIN PLAN 실행
        cursor.execute(
            f"EXPLAIN PLAN SET STATEMENT_ID = '{stmt_id}' FOR {sql}"
        )

        # DBMS_XPLAN.DISPLAY 로 실행계획 조회
        cursor.execute(
            "SELECT PLAN_TABLE_OUTPUT "
            "FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', null, 'serial'))"
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
