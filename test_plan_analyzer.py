"""plan_analyzer.py 단위 테스트 (Oracle 접속 없이 실행 가능)."""
import unittest
from unittest.mock import MagicMock, call
from plan_analyzer import (
    get_plan_hash,
    parse_plan_steps,
    explain_plan,
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

    def test_pre_delete_called(self):
        """실행 전 DELETE 가 호출되는지 확인."""
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        conn, cursor = self._make_mock_conn(plan_rows)

        explain_plan(conn, "SELECT * FROM TABS", db_id=0, db_label="DB1")

        delete_calls = [
            str(c) for c in cursor.execute.call_args_list
            if "DELETE" in str(c).upper()
        ]
        self.assertTrue(len(delete_calls) >= 1, "사전 DELETE 가 호출되지 않았습니다.")

    def test_no_post_delete(self):
        """결과 조회 후 DELETE 가 한 번만(사전 1회) 호출되는지 확인."""
        plan_rows = [(line,) for line in SAMPLE_PLAN.splitlines()]
        conn, cursor = self._make_mock_conn(plan_rows)

        explain_plan(conn, "SELECT * FROM TABS", db_id=0, db_label="DB1")

        delete_calls = [
            c for c in cursor.execute.call_args_list
            if "DELETE" in str(c).upper()
        ]
        self.assertEqual(len(delete_calls), 1, "DELETE 는 사전 1회만 호출돼야 합니다.")


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
        cursor.execute.side_effect = [None, Exception("ORA-00942: table or view does not exist")]
        conn = MagicMock()
        conn.cursor.return_value = cursor
        result = explain_plan(conn, "SELECT * FROM NO_SUCH_TABLE", db_id=0, db_label="DB1")
        self.assertFalse(result.success)
        self.assertIn("ORA-00942", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
