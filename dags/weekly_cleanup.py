"""
dags/weekly_cleanup.py

SKILL: Apache Airflow DAG, database maintenance, scheduled cleanup

Weekly cleanup DAG that keeps the database healthy.

Schedule: 2am every Sunday (0 2 * * 0)

Pipeline:
  1. cleanup_old_jobs    → delete evaluation jobs older than 30 days
  2. log_cleanup_stats   → log what was cleaned up
"""

from datetime import datetime, timedelta
import logging

import psycopg2
import psycopg2.extras

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "promptvault",
    "user": "promptvault_user",
    "password": "promptvault_pass",
}


def cleanup_old_evaluation_jobs(**context) -> None:
    """
    Task 1: Remove evaluation jobs older than 30 days.

    SKILL: Database maintenance, soft delete vs hard delete

    WHY DELETE OLD JOBS:
      Evaluation jobs accumulate fast. If we run nightly on 100 prompts,
      that is 3,000 rows per month. After a year: 36,000 rows.
      Old evaluation history beyond 30 days is rarely needed.
      Keeping old rows slows queries and wastes disk space.

    WHY HARD DELETE HERE (not soft delete):
      Evaluation jobs are logs, not business entities.
      Unlike prompts and workspaces (which we soft delete),
      old log entries can be permanently deleted safely.
      We only keep the most recent 30 days of history.
    """
    ti = context["ti"]
    run_date = context["ds"]

    logger.info(
        f"[cleanup_old_evaluation_jobs] Starting cleanup for {run_date}"
    )

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    try:
        # Count jobs to be deleted (for the report)
        cursor.execute("""
            SELECT COUNT(*)
            FROM evaluation_jobs
            WHERE created_at < NOW() - INTERVAL '30 days'
        """)
        count_to_delete = cursor.fetchone()[0]

        if count_to_delete == 0:
            logger.info(
                "[cleanup_old_evaluation_jobs] No old jobs to delete"
            )
            ti.xcom_push(key="deleted_count", value=0)
            return

        # Delete old completed/failed jobs
        cursor.execute("""
            DELETE FROM evaluation_jobs
            WHERE created_at < NOW() - INTERVAL '30 days'
              AND status IN ('completed', 'failed')
        """)

        deleted_count = cursor.rowcount
        conn.commit()

        logger.info(
            f"[cleanup_old_evaluation_jobs] "
            f"Deleted {deleted_count} old evaluation jobs"
        )

        ti.xcom_push(key="deleted_count", value=deleted_count)
        ti.xcom_push(key="found_count", value=count_to_delete)

    except Exception as e:
        conn.rollback()
        logger.error(f"[cleanup_old_evaluation_jobs] Error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def get_database_stats(**context) -> None:
    """
    Task 2: Log database statistics after cleanup.

    SKILL: Database monitoring, row count queries

    Shows current state of each table after cleanup.
    In production this would write to a metrics dashboard.
    """
    ti = context["ti"]
    deleted_count = ti.xcom_pull(
        task_ids="cleanup_old_evaluation_jobs",
        key="deleted_count"
    ) or 0

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Get row counts for all main tables
        tables = ["workspaces", "prompts", "evaluation_jobs"]
        stats = {}

        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]

        # Get evaluation jobs breakdown by status
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM evaluation_jobs
            GROUP BY status
            ORDER BY count DESC
        """)
        status_breakdown = {row["status"]: row["count"]
                           for row in cursor.fetchall()}

        report = f"""
╔══════════════════════════════════════════════════════════╗
║       PROMPTVAULT WEEKLY CLEANUP REPORT                  ║
╠══════════════════════════════════════════════════════════╣
║  Jobs Deleted (>30 days):    {deleted_count}
╠══════════════════════════════════════════════════════════╣
║  DATABASE TABLE SIZES:
║    workspaces:       {stats.get('workspaces', 0)} rows
║    prompts:          {stats.get('prompts', 0)} rows
║    evaluation_jobs:  {stats.get('evaluation_jobs', 0)} rows
╠══════════════════════════════════════════════════════════╣
║  EVALUATION JOBS BY STATUS:
"""
        for status, count in status_breakdown.items():
            report += f"║    {status}: {count}\n"

        report += "╚══════════════════════════════════════════════════════════╝"
        logger.info(report)

    finally:
        cursor.close()
        conn.close()


# ── DAG DEFINITION ────────────────────────────────────────────────────
default_args = {
    "owner": "promptvault",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}

with DAG(
    dag_id="weekly_cleanup",
    description="Weekly database cleanup and maintenance",
    schedule_interval="0 2 * * 0",    # 2am every Sunday
    start_date=datetime(2026, 1, 1),
    default_args=default_args,
    catchup=False,
    max_active_runs=1,
    tags=["promptvault", "maintenance", "weekly"],
) as dag:

    t1_cleanup = PythonOperator(
        task_id="cleanup_old_evaluation_jobs",
        python_callable=cleanup_old_evaluation_jobs,
        provide_context=True,
    )

    t2_stats = PythonOperator(
        task_id="get_database_stats",
        python_callable=get_database_stats,
        provide_context=True,
    )

    t1_cleanup >> t2_stats