"""plan_analyzer.py 단위 테스트 (Oracle 접속 없이 실행 가능)."""
import unittest
from unittest.mock import MagicMock, call
from plan_analyzer import (
    get_plan_hash,
    parse_plan_steps,
    explain_plan,
    bind_string_literals,
    PlanResult,
)

# ── 샘플 DBMS_XPLAN.DISPLAY 출력 ──────────────────────────────────────────────
SAMPLE_PLAN = """\
Plan hash value: 1234567890

---------------------------------------------------------------------------
| Id  | Operation         | Name  | Rows  | Bytes | Cost (%CPU)| Time     |
---------------------------------------------------------------------------
|   0 | SELECT STATEMENT  |       |     1 |    87 |     3   (0)| 00:00:01 |
|   1 |  TABLE ACCESS FULL| TABS  |     1 |    87 |     3   (0)| 00:00:01 |
---------------------------------------------------------------------------
"""

SAMPLE_PLAN_NO_HASH = """\
---------------------------------------------------------------------------
| Id  | Operation         | Name  | Rows  | Bytes | Cost (%CPU)| Time     |
---------------------------------------------------------------------------
|   0 | SELECT STATEMENT  |       |     1 |    87 |     3   (0)| 00:00:01 |
---------------------------------------------------------------------------
"""


class TestGetPlanHash(unittest.TestCase):
    def test_hash_found(self):
        self.assertEqual(get_plan_hash(SAMPLE_PLAN), "1234567890")

    def test_hash_not_found(self):
        self.assertIsNone(get_plan_hash(SAMPLE_PLAN_NO_HASH))

    def test_hash_case_insensitive(self):
        text = "plan Hash Value: 9999"
        self.assertEqual(get_plan_hash(text), "9999")


class TestParsePlanSteps(unittest.TestCase):
    def test_steps_parsed(self):
        steps = parse_plan_steps(SAMPLE_PLAN)
        self.assertGreaterEqual(len(steps), 1)

    def test_step_fields(self):
        steps = parse_plan_steps(SAMPLE_PLAN)
        ids = [s.id for s in steps]
        self.assertIn(0, ids)


class TestStatementId(unittest.TestCase):
    """STATEMENT_ID 가 DB별 고정값(OPA1~OPA6)인지 확인."""

    def _make_mock_conn(self, plan_rows):
        """fetchall 이 plan_rows 를 반환하는 mock connection."""
        cursor = MagicMock()
        cursor.fetchall.return_value = plan_rows
        conn = MagicMock()
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_statement_id_opa1(self):
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        conn, cursor = self._make_mock_conn(plan_rows)

        result = explain_plan(conn, "SELECT * FROM TABS", db_id=0, db_label="DB1")

        # EXPLAIN PLAN 호출 인자에 'OPA1' 이 포함돼야 함
        explain_calls = [
            str(c) for c in cursor.execute.call_args_list
            if "EXPLAIN PLAN" in str(c).upper()
        ]
        self.assertTrue(
            any("OPA1" in c for c in explain_calls),
            f"STATEMENT_ID OPA1 not found in calls: {cursor.execute.call_args_list}",
        )

    def test_statement_id_opa3(self):
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        conn, cursor = self._make_mock_conn(plan_rows)

        explain_plan(conn, "SELECT * FROM TABS", db_id=2, db_label="DB3")

        explain_calls = [
            str(c) for c in cursor.execute.call_args_list
            if "EXPLAIN PLAN" in str(c).upper()
        ]
        self.assertTrue(
            any("OPA3" in c for c in explain_calls),
            f"STATEMENT_ID OPA3 not found in calls: {cursor.execute.call_args_list}",
        )

    def test_no_delete_called(self):
        """DELETE 가 전혀 호출되지 않는지 확인."""
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        conn, cursor = self._make_mock_conn(plan_rows)

        explain_plan(conn, "SELECT * FROM TABS", db_id=0, db_label="DB1")

        delete_calls = [
            c for c in cursor.execute.call_args_list
            if "DELETE" in str(c).upper()
        ]
        self.assertEqual(len(delete_calls), 0, "PLAN_TABLE DELETE 가 호출되면 안 됩니다.")


class TestExplainPlanResult(unittest.TestCase):
    def _make_mock_conn(self, plan_rows):
        cursor = MagicMock()
        cursor.fetchall.return_value = plan_rows
        conn = MagicMock()
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_success(self):
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        conn, _ = self._make_mock_conn(plan_rows)
        result = explain_plan(conn, "SELECT * FROM TABS", db_id=0, db_label="DB1")
        self.assertTrue(result.success)
        self.assertEqual(result.plan_hash, "1234567890")
        self.assertIsNone(result.error)

    def test_empty_sql(self):
        conn = MagicMock()
        result = explain_plan(conn, "   ", db_id=0, db_label="DB1")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_db_error(self):
        cursor = MagicMock()
        # ALTER SESSION dynamic_sampling(0), ALTER SESSION adaptive_statistics,
        # EXPLAIN PLAN, DBMS_XPLAN.DISPLAY 순서
        # EXPLAIN PLAN 에서 ORA-00942 발생 시뮬레이션
        cursor.execute.side_effect = [
            None,   # ALTER SESSION optimizer_dynamic_sampling = 0
            None,   # ALTER SESSION optimizer_adaptive_statistics (12c+)
            Exception("ORA-00942: table or view does not exist"),  # EXPLAIN PLAN
        ]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        result = explain_plan(conn, "SELECT * FROM NO_SUCH_TABLE", db_id=0, db_label="DB1")
        self.assertFalse(result.success)
        self.assertIn("ORA-00942", result.error)


class TestBindStringLiterals(unittest.TestCase):
    """bind_string_literals() 단위 테스트."""

    def test_single_literal(self):
        sql = "SELECT * FROM emp WHERE ename = 'SCOTT'"
        converted, binds = bind_string_literals(sql)
        self.assertIn(":v1", converted)
        self.assertNotIn("'SCOTT'", converted)
        self.assertEqual(binds[":v1"], "'SCOTT'")

    def test_multiple_literals(self):
        sql = "SELECT * FROM emp WHERE deptno = '10' AND ename = 'SCOTT'"
        converted, binds = bind_string_literals(sql)
        self.assertIn(":v1", converted)
        self.assertIn(":v2", converted)
        self.assertEqual(len(binds), 2)

    def test_no_literals(self):
        sql = "SELECT * FROM emp WHERE deptno = 10"
        converted, binds = bind_string_literals(sql)
        self.assertEqual(converted, sql)
        self.assertEqual(len(binds), 0)

    def test_date_literal_preserved(self):
        """DATE 'xxx' 는 치환하지 않음."""
        sql = "SELECT * FROM emp WHERE hiredate = DATE '2024-01-01'"
        converted, binds = bind_string_literals(sql)
        self.assertIn("DATE '2024-01-01'", converted)
        self.assertEqual(len(binds), 0)

    def test_timestamp_literal_preserved(self):
        """TIMESTAMP 'xxx' 는 치환하지 않음."""
        sql = "SELECT * FROM t WHERE ts = TIMESTAMP '2024-01-01 00:00:00'"
        converted, binds = bind_string_literals(sql)
        self.assertIn("TIMESTAMP '2024-01-01 00:00:00'", converted)
        self.assertEqual(len(binds), 0)

    def test_mixed_date_and_string(self):
        """DATE 리터럴은 유지, 일반 문자열은 치환."""
        sql = "SELECT * FROM emp WHERE hiredate > DATE '2024-01-01' AND ename = 'SCOTT'"
        converted, binds = bind_string_literals(sql)
        self.assertIn("DATE '2024-01-01'", converted)
        self.assertIn(":v1", converted)
        self.assertEqual(len(binds), 1)
        self.assertEqual(binds[":v1"], "'SCOTT'")

    def test_escaped_quote_in_literal(self):
        """내부 '' 이스케이프 처리."""
        sql = "SELECT * FROM t WHERE name = 'O''Brien'"
        converted, binds = bind_string_literals(sql)
        self.assertIn(":v1", converted)
        self.assertEqual(binds[":v1"], "'O''Brien'")

    def test_explain_plan_uses_converted_sql(self):
        """use_bind_vars=True 일 때 치환된 SQL 로 EXPLAIN PLAN 실행."""
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        cursor = MagicMock()
        cursor.fetchall.return_value = plan_rows
        conn = MagicMock()
        conn.cursor.return_value = cursor

        explain_plan(conn, "SELECT * FROM emp WHERE ename = 'SCOTT'",
                     db_id=0, db_label="DB1", use_bind_vars=True)

        explain_calls = [
            str(c) for c in cursor.execute.call_args_list
            if "EXPLAIN PLAN" in str(c).upper()
        ]
        self.assertTrue(
            any(":v1" in c and "'SCOTT'" not in c for c in explain_calls),
            f"치환된 SQL(:v1)이 EXPLAIN PLAN 에 사용되지 않았습니다.\n{explain_calls}",
        )

    def test_explain_plan_original_sql_when_unchecked(self):
        """use_bind_vars=False 일 때 원본 SQL 그대로 EXPLAIN PLAN 실행."""
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        cursor = MagicMock()
        cursor.fetchall.return_value = plan_rows
        conn = MagicMock()
        conn.cursor.return_value = cursor

        explain_plan(conn, "SELECT * FROM emp WHERE ename = 'SCOTT'",
                     db_id=0, db_label="DB1", use_bind_vars=False)

        explain_calls = [
            str(c) for c in cursor.execute.call_args_list
            if "EXPLAIN PLAN" in str(c).upper()
        ]
        self.assertTrue(
            any("'SCOTT'" in c for c in explain_calls),
            f"원본 SQL이 EXPLAIN PLAN 에 사용되어야 합니다.\n{explain_calls}",
        )

    def test_result_stores_bind_map(self):
        """PlanResult 에 bind_map 이 저장되는지 확인."""
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        cursor = MagicMock()
        cursor.fetchall.return_value = plan_rows
        conn = MagicMock()
        conn.cursor.return_value = cursor

        result = explain_plan(conn, "SELECT * FROM emp WHERE ename = 'SCOTT'",
                              db_id=0, db_label="DB1", use_bind_vars=True)
        self.assertIn(":v1", result.bind_map)
        self.assertEqual(result.bind_map[":v1"], "'SCOTT'")

    def test_bind_map_empty_when_unchecked(self):
        """use_bind_vars=False 일 때 bind_map 이 비어 있는지 확인."""
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        cursor = MagicMock()
        cursor.fetchall.return_value = plan_rows
        conn = MagicMock()
        conn.cursor.return_value = cursor

        result = explain_plan(conn, "SELECT * FROM emp WHERE ename = 'SCOTT'",
                              db_id=0, db_label="DB1", use_bind_vars=False)
        self.assertEqual(len(result.bind_map), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
