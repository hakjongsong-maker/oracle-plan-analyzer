"""Analyze plan differences across DBs and generate tuning guidance."""
from __future__ import annotations
import re
from typing import List, Optional, Dict
from plan_analyzer import PlanResult, extract_operations


HINT_EXPLANATIONS = {
    "INDEX": "특정 인덱스를 강제로 사용하게 합니다.",
    "FULL": "테이블 전체 스캔을 강제합니다.",
    "USE_NL": "Nested Loop Join을 강제합니다. 소량 데이터에 유리합니다.",
    "USE_HASH": "Hash Join을 강제합니다. 대량 데이터에 유리합니다.",
    "USE_MERGE": "Sort Merge Join을 강제합니다.",
    "NO_MERGE": "인라인 뷰의 머지를 방지합니다.",
    "GATHER_PLAN_STATISTICS": "실행 통계를 수집합니다.",
    "CARDINALITY": "옵티마이저 카디널리티 추정을 수동으로 보정합니다.",
    "OPT_PARAM": "옵티마이저 파라미터를 쿼리 레벨에서 설정합니다.",
    "NO_PARALLEL": "병렬 실행을 비활성화합니다.",
    "PARALLEL": "병렬 실행을 활성화합니다.",
    "LEADING": "조인 순서를 강제합니다.",
    "NO_USE_HASH": "Hash Join을 비활성화합니다.",
    "NO_USE_NL": "Nested Loop Join을 비활성화합니다.",
}


def _extract_tables(plan_text: str) -> List[str]:
    tables = []
    for line in plan_text.splitlines():
        m = re.search(r"TABLE ACCESS\s+(?:FULL|BY INDEX ROWID BATCHED|BY INDEX ROWID)\s*\|\s*(\w+)", line, re.IGNORECASE)
        if m:
            tables.append(m.group(1).upper())
    return list(set(tables))


def _extract_indexes(plan_text: str) -> Dict[str, str]:
    """Return {table: index_name} pairs where index access occurs."""
    result = {}
    for line in plan_text.splitlines():
        m = re.search(r"INDEX (?:RANGE|UNIQUE|FULL|FAST FULL|SKIP) SCAN\s*\|\s*(\w+)", line, re.IGNORECASE)
        if m:
            result[m.group(1).upper()] = m.group(1).upper()
    return result


def _detect_full_scans(plan_text: str) -> List[str]:
    tables = []
    for line in plan_text.splitlines():
        m = re.search(r"TABLE ACCESS FULL\s*\|\s*(\w+)", line, re.IGNORECASE)
        if m:
            tables.append(m.group(1).upper())
    return tables


def _detect_join_methods(plan_text: str) -> List[str]:
    methods = []
    for line in plan_text.splitlines():
        upper = line.upper()
        if "NESTED LOOPS" in upper:
            methods.append("NESTED LOOPS")
        elif "HASH JOIN" in upper:
            methods.append("HASH JOIN")
        elif "SORT MERGE JOIN" in upper or ("MERGE JOIN" in upper and "CARTESIAN" not in upper):
            methods.append("SORT MERGE JOIN")
    return list(set(methods))


def _detect_cardinality_issues(plan_texts: List[str]) -> bool:
    """Check if cardinality estimates differ significantly across plans."""
    row_counts = []
    pattern = re.compile(r"\|\s*\d+\s*\|\s*[\w\s]+\s*\|\s*[\w$#\s]*\s*\|\s*([\d KMG]+)\s*\|")
    for pt in plan_texts:
        counts = []
        for line in pt.splitlines():
            m = pattern.match(line.strip())
            if m:
                counts.append(m.group(1).strip())
        row_counts.append(counts)
    # If row counts differ across DBs for the same plan step → cardinality issue
    if len(row_counts) >= 2:
        for i in range(min(len(r) for r in row_counts)):
            vals = [r[i] for r in row_counts if i < len(r)]
            if len(set(vals)) > 1:
                return True
    return False


def analyze_plans(results: List[PlanResult]) -> str:
    """
    Compare execution plans across DBs and produce a tuning guide string.
    """
    successful = [r for r in results if r.success and r.plan_hash]
    if not successful:
        return "실행계획을 가져온 DB가 없습니다."

    if len(successful) == 1:
        return f"접속된 DB가 1개입니다. 비교할 수 없습니다.\n\n[{successful[0].db_label}] Plan hash: {successful[0].plan_hash}"

    hashes = {r.plan_hash for r in successful}

    # ── All identical ──────────────────────────────────────────────────────────
    if len(hashes) == 1:
        hash_val = next(iter(hashes))
        lines = ["=" * 60]
        lines.append("✅  모든 DB의 실행계획(Plan hash value)이 동일합니다.")
        lines.append(f"    Plan hash value: {hash_val}")
        lines.append("=" * 60)
        lines.append("\n별도의 튜닝이 필요하지 않습니다.")
        return "\n".join(lines)

    # ── Plans differ ──────────────────────────────────────────────────────────
    lines = ["=" * 60]
    lines.append("⚠️  DB 간 실행계획(Plan hash value)이 다릅니다!")
    lines.append("=" * 60)

    # Show hash per DB
    lines.append("\n[DB별 Plan hash value]")
    hash_groups: Dict[str, List[str]] = {}
    for r in successful:
        hash_groups.setdefault(r.plan_hash, []).append(r.db_label)
        lines.append(f"  • {r.db_label:20s}  →  {r.plan_hash}")

    # Majority hash (most DBs share this)
    majority_hash = max(hash_groups, key=lambda h: len(hash_groups[h]))
    minority_dbs = [r for r in successful if r.plan_hash != majority_hash]
    majority_dbs = [r for r in successful if r.plan_hash == majority_hash]

    lines.append(f"\n[기준 Plan hash: {majority_hash}]")
    lines.append(f"  기준 DB: {', '.join(r.db_label for r in majority_dbs)}")
    lines.append(f"  비정상 DB: {', '.join(r.db_label for r in minority_dbs)}")

    # ── Difference analysis ───────────────────────────────────────────────────
    lines.append("\n" + "─" * 60)
    lines.append("📋  실행계획 차이 분석")
    lines.append("─" * 60)

    ref_plan = majority_dbs[0].plan_text
    ref_ops = extract_operations(ref_plan)

    all_hints = set()
    hint_block: List[str] = []

    for bad_r in minority_dbs:
        bad_ops = extract_operations(bad_r.plan_text)
        diff_lines = []

        # Access path differences
        ref_full = set(_detect_full_scans(ref_plan))
        bad_full = set(_detect_full_scans(bad_r.plan_text))
        ref_idx = set(_extract_indexes(ref_plan).keys())
        bad_idx = set(_extract_indexes(bad_r.plan_text).keys())

        extra_full = bad_full - ref_full
        missing_idx = ref_idx - bad_idx

        if extra_full:
            for tbl in sorted(extra_full):
                diff_lines.append(
                    f"  ▶ [{bad_r.db_label}] {tbl} 테이블에 FULL SCAN 발생 "
                    f"(기준 DB는 인덱스 사용)"
                )
                all_hints.add(f"INDEX({tbl})")

        if missing_idx:
            for idx in sorted(missing_idx):
                diff_lines.append(
                    f"  ▶ [{bad_r.db_label}] 인덱스 {idx} 미사용"
                )
                all_hints.add(f"INDEX({idx})")

        # Join method differences
        ref_joins = set(_detect_join_methods(ref_plan))
        bad_joins = set(_detect_join_methods(bad_r.plan_text))
        join_diff = ref_joins.symmetric_difference(bad_joins)
        if join_diff:
            diff_lines.append(
                f"  ▶ [{bad_r.db_label}] 조인 방법 차이: "
                f"기준={','.join(ref_joins) or '없음'} / "
                f"비정상={','.join(bad_joins) or '없음'}"
            )
            for j in ref_joins:
                if j == "NESTED LOOPS":
                    all_hints.add("USE_NL(table1 table2)")
                elif j == "HASH JOIN":
                    all_hints.add("USE_HASH(table1 table2)")
                elif j == "SORT MERGE JOIN":
                    all_hints.add("USE_MERGE(table1 table2)")

        if not diff_lines:
            diff_lines.append(
                f"  ▶ [{bad_r.db_label}] 세부 연산은 유사하나 비용 추정 값이 다릅니다.\n"
                f"    → 통계 정보(DBMS_STATS) 불일치일 가능성이 높습니다."
            )
            all_hints.add("CARDINALITY(table 1000)")
            all_hints.add("OPT_PARAM('optimizer_features_enable' '12.2.0.1')")

        lines.extend(diff_lines)

    # ── Root cause analysis ───────────────────────────────────────────────────
    lines.append("\n" + "─" * 60)
    lines.append("🔍  주요 원인 분석")
    lines.append("─" * 60)

    plan_texts_all = [r.plan_text for r in successful]
    has_cardinality_issue = _detect_cardinality_issues(plan_texts_all)

    causes = []
    if has_cardinality_issue:
        causes.append(
            "1. 통계 정보(Statistics) 불일치\n"
            "   DB마다 테이블/인덱스 통계의 수집 시점이나 설정이 달라\n"
            "   옵티마이저의 카디널리티 추정이 다릅니다.\n"
            "   → 해결: DBMS_STATS.GATHER_TABLE_STATS로 모든 DB에서\n"
            "            동일한 통계를 수집하거나 PENDING 통계를 동기화"
        )

    # Check if optimizer version differs (can't know without querying V$PARAMETER, but hint)
    causes.append(
        "2. 옵티마이저 파라미터 차이\n"
        "   OPTIMIZER_FEATURES_ENABLE, OPTIMIZER_MODE, DB_FILE_MULTIBLOCK_READ_COUNT 등\n"
        "   초기화 파라미터 값이 다를 경우 서로 다른 플랜이 선택됩니다.\n"
        "   → 해결: 다음 쿼리로 차이 확인:\n"
        "     SELECT NAME, VALUE FROM V$PARAMETER\n"
        "     WHERE NAME LIKE '%optimizer%' ORDER BY 1;"
    )

    causes.append(
        "3. 인덱스 구조/존재 여부 차이\n"
        "   한쪽 DB에만 인덱스가 있거나 인덱스 칼럼 순서가 다를 경우\n"
        "   서로 다른 액세스 경로가 선택됩니다.\n"
        "   → 해결: 모든 DB에 동일한 인덱스 DDL 적용"
    )

    for c in causes:
        lines.append("\n" + c)

    # ── SQL Hints guide ───────────────────────────────────────────────────────
    lines.append("\n" + "─" * 60)
    lines.append("💡  SQL 힌트를 이용한 플랜 고정 방법")
    lines.append("─" * 60)
    lines.append(
        "모든 DB에서 기준 플랜과 동일하게 실행하려면 아래 힌트를 쿼리에 추가하세요.\n"
        "힌트는 쿼리 특성에 맞게 선택적으로 적용하세요.\n"
    )

    lines.append("[권장 힌트 목록]")
    for hint in sorted(all_hints):
        base = re.match(r"(\w+)", hint)
        desc = HINT_EXPLANATIONS.get(base.group(1) if base else hint, "")
        lines.append(f"  /*+ {hint} */")
        if desc:
            lines.append(f"       → {desc}")

    lines.append("\n[힌트 적용 예시]")
    lines.append(
        "  SELECT /*+ <힌트> */\n"
        "         col1, col2\n"
        "  FROM   your_table\n"
        "  WHERE  ..."
    )

    # ── SQL Profile / Baseline ────────────────────────────────────────────────
    lines.append("\n" + "─" * 60)
    lines.append("🔧  영구적 플랜 고정 방법 (SQL Profile / SQL Plan Baseline)")
    lines.append("─" * 60)
    lines.append(
        "힌트 수정이 어려운 경우 아래 방법으로 플랜을 DB에 영구 고정할 수 있습니다.\n"
        "\n"
        "① SQL Plan Baseline 수동 등록 (권장)\n"
        "   BEGIN\n"
        "     DBMS_SPM.LOAD_PLANS_FROM_CURSOR_CACHE(\n"
        "       sql_id       => '<SQL_ID>',\n"
        "       plan_hash_value => <PLAN_HASH>,\n"
        "       fixed        => 'YES'\n"
        "     );\n"
        "   END;\n"
        "   /\n"
        "\n"
        "② SQL Profile 생성 (DBMS_SQLTUNE)\n"
        "   DECLARE\n"
        "     v_taskname VARCHAR2(30);\n"
        "   BEGIN\n"
        "     v_taskname := DBMS_SQLTUNE.CREATE_TUNING_TASK(\n"
        "       sql_text => '<YOUR SQL>'\n"
        "     );\n"
        "     DBMS_SQLTUNE.EXECUTE_TUNING_TASK(v_taskname);\n"
        "     DBMS_SQLTUNE.ACCEPT_SQL_PROFILE(\n"
        "       task_name => v_taskname,\n"
        "       force_match => TRUE\n"
        "     );\n"
        "   END;\n"
        "   /\n"
        "\n"
        "③ 통계 동기화 스크립트 (모든 DB에서 동일한 통계 적용)\n"
        "   -- 소스 DB에서 통계 Export\n"
        "   EXEC DBMS_STATS.CREATE_STAT_TABLE('STAT_OWNER', 'STAT_TABLE');\n"
        "   EXEC DBMS_STATS.EXPORT_TABLE_STATS('SCHEMA', 'TABLE_NAME',\n"
        "        stattab => 'STAT_TABLE', statown => 'STAT_OWNER');\n"
        "   -- 타겟 DB에 Import\n"
        "   EXEC DBMS_STATS.IMPORT_TABLE_STATS('SCHEMA', 'TABLE_NAME',\n"
        "        stattab => 'STAT_TABLE', statown => 'STAT_OWNER');\n"
    )

    return "\n".join(lines)
