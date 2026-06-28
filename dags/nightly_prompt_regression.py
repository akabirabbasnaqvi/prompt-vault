"""
dags/nightly_prompt_regression.py

SKILL: Apache Airflow DAG, PythonOperator, XCom, scheduling, cron

Nightly DAG that evaluates all active prompts automatically.

Schedule: midnight every night (0 0 * * *)

Pipeline:
  1. fetch_active_prompts   → query DB for all active prompts
  2. dispatch_evaluations   → send each prompt to Celery for evaluation
  3. wait_for_completions   → poll until all jobs are done (or timeout)
  4. generate_report        → log quality summary

WHY THIS IS VALUABLE:
  Without this, prompt quality degradation is invisible.
  A prompt that scored 0.9 last month might score 0.6 today
  because the underlying model changed, and no one would know.
  This DAG catches regressions automatically — every single night.

This is the same pattern Netflix uses to run model quality checks,
Airbnb uses for data pipeline validation, and Stripe uses for
financial reconciliation — all scheduled, all automated.
"""

from datetime import datetime, timedelta, timezone
import logging
import time
import json

import psycopg2
import psycopg2.extras
import redis as redis_lib

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# DATABASE CONNECTION HELPER
#
# Airflow runs as a separate process from FastAPI.
# We connect to the same PostgreSQL database directly using psycopg2.
# In production, these credentials come from Airflow Connections
# (configured in the Airflow UI) not hardcoded here.
# For development, we hardcode them.
# ─────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "promptvault",
    "user": "promptvault_user",
    "password": "promptvault_pass",
}

REDIS_CONFIG = {
    "host": "localhost",
    "port": 6379,
    "db": 1,    # DB 1 = Celery broker
    "decode_responses": True,
}

# ─────────────────────────────────────────────────────────────────────
# TASK FUNCTIONS
#
# Each function below becomes one task in the DAG.
# The `ti` (TaskInstance) parameter gives us access to XCom.
# ─────────────────────────────────────────────────────────────────────

def fetch_active_prompts(**context) -> None:
    """
    Task 1: Fetch all active prompts from the database.

    SKILL: Airflow task, XCom push, psycopg2

    Queries for prompts that:
    - belong to active workspaces
    - are themselves active
    - have status = 'active' (not draft or archived)

    Pushes list of prompt data to XCom for the next task to use.
    """
    ti = context["ti"]
    run_date = context["ds"]   # Airflow provides the run date as "ds"

    logger.info(f"[fetch_active_prompts] Starting for run date: {run_date}")

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        cursor.execute("""
            SELECT
                p.id::text AS prompt_id,
                p.name AS prompt_name,
                p.slug AS prompt_slug,
                p.description AS prompt_description,
                w.slug AS workspace_slug
            FROM prompts p
            JOIN workspaces w ON w.id = p.workspace_id
            WHERE p.is_active = true
              AND p.status = 'active'
              AND w.is_active = true
            ORDER BY p.created_at DESC
        """)

        rows = cursor.fetchall()
        prompts = [dict(row) for row in rows]

        logger.info(
            f"[fetch_active_prompts] Found {len(prompts)} active prompts"
        )

        # XCom push — store the data for the next task
        ti.xcom_push(key="active_prompts", value=prompts)
        ti.xcom_push(key="prompt_count", value=len(prompts))

        return len(prompts)

    finally:
        cursor.close()
        conn.close()


def dispatch_evaluation_jobs(**context) -> None:
    """
    Task 2: Create evaluation jobs and dispatch Celery tasks.

    SKILL: Airflow task, XCom pull, Celery task dispatch

    For each active prompt:
    1. Creates an evaluation_jobs record in PostgreSQL (status=pending)
    2. Dispatches a Celery task to process it

    WHY CREATE DB RECORD FIRST:
      Same reason as in Step 6 — we want a permanent audit trail
      even if Celery is temporarily unavailable.
    """
    ti = context["ti"]

    # XCom pull — get the prompts from Task 1
    prompts = ti.xcom_pull(
        task_ids="fetch_active_prompts",
        key="active_prompts"
    )

    if not prompts:
        logger.info("[dispatch_evaluation_jobs] No active prompts to evaluate")
        ti.xcom_push(key="job_ids", value=[])
        return

    logger.info(
        f"[dispatch_evaluation_jobs] Dispatching {len(prompts)} evaluations"
    )

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    job_ids = []

    try:
        for prompt in prompts:
            # Create a standard test input for regression testing
            test_input = (
                f"Nightly regression test for prompt: {prompt['prompt_name']}. "
                f"Evaluate this prompt's clarity, specificity, and expected output quality."
            )

            # Insert evaluation job record
            cursor.execute("""
                INSERT INTO evaluation_jobs
                    (id, prompt_id, status, test_input, created_at)
                VALUES
                    (gen_random_uuid(), %s::uuid, 'pending', %s, NOW())
                RETURNING id::text
            """, (prompt["prompt_id"], test_input))

            job_id = cursor.fetchone()[0]
            job_ids.append({
                "job_id": job_id,
                "prompt_id": prompt["prompt_id"],
                "test_input": test_input,
            })

            conn.commit()

            # ── DISPATCH CELERY TASK ──────────────────────────────────
            # We use Celery's send_task() which pushes a message to
            # the Redis broker queue without needing to import the task.
            # This keeps Airflow loosely coupled from our FastAPI app.
            # The Celery worker picks it up automatically.
            import celery as celery_lib
            from celery import Celery

            celery_app = Celery(
                "promptvault",
                broker="redis://localhost:6379/1",
                backend="redis://localhost:6379/2",
            )

            celery_app.send_task(
                "evaluate_prompt",
                kwargs={
                    "job_id": job_id,
                    "prompt_id": prompt["prompt_id"],
                    "test_input": test_input,
                },
            )

            logger.info(
                f"[dispatch_evaluation_jobs] Dispatched job {job_id} "
                f"for prompt '{prompt['prompt_slug']}'"
            )

        # Push all job IDs for the next task
        ti.xcom_push(key="job_ids", value=job_ids)
        logger.info(
            f"[dispatch_evaluation_jobs] All {len(job_ids)} jobs dispatched"
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"[dispatch_evaluation_jobs] Error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def wait_for_completions(**context) -> None:
    """
    Task 3: Wait until all dispatched jobs complete.

    SKILL: Airflow task, polling pattern, timeout handling

    Polls the database every 10 seconds until:
    - All jobs are completed or failed, OR
    - 10 minutes have passed (timeout)

    WHY POLL THE DATABASE, NOT CELERY:
      Our Celery task updates the database when it finishes.
      The database is our single source of truth.
      Polling the DB is simpler and more reliable than
      querying Celery's result backend directly.
    """
    ti = context["ti"]
    job_data = ti.xcom_pull(
        task_ids="dispatch_evaluation_jobs",
        key="job_ids"
    )

    if not job_data:
        logger.info("[wait_for_completions] No jobs to wait for")
        return

    job_ids = [j["job_id"] for j in job_data]
    logger.info(
        f"[wait_for_completions] Waiting for {len(job_ids)} jobs to complete"
    )

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    timeout_seconds = 600   # 10 minute maximum wait
    poll_interval = 10      # Check every 10 seconds
    elapsed = 0

    try:
        while elapsed < timeout_seconds:
            # Query status of all our jobs
            placeholders = ",".join(["%s"] * len(job_ids))
            cursor.execute(f"""
                SELECT
                    id::text,
                    status,
                    score,
                    error_message
                FROM evaluation_jobs
                WHERE id::text IN ({placeholders})
            """, job_ids)

            rows = cursor.fetchall()
            statuses = {row["id"]: row["status"] for row in rows}

            pending = [
                jid for jid, s in statuses.items()
                if s in ("pending", "running")
            ]

            completed = [
                jid for jid, s in statuses.items()
                if s == "completed"
            ]

            failed = [
                jid for jid, s in statuses.items()
                if s == "failed"
            ]

            logger.info(
                f"[wait_for_completions] "
                f"Pending: {len(pending)} | "
                f"Completed: {len(completed)} | "
                f"Failed: {len(failed)} | "
                f"Elapsed: {elapsed}s"
            )

            if not pending:
                logger.info(
                    f"[wait_for_completions] All jobs finished. "
                    f"Completed: {len(completed)}, Failed: {len(failed)}"
                )
                break

            time.sleep(poll_interval)
            elapsed += poll_interval

        else:
            logger.warning(
                f"[wait_for_completions] Timeout after {timeout_seconds}s. "
                f"Some jobs may still be running."
            )

        # Push final results for the report task
        cursor.execute(f"""
            SELECT
                id::text,
                status,
                score,
                evaluation_summary
            FROM evaluation_jobs
            WHERE id::text IN ({placeholders})
        """, job_ids)

        final_results = [dict(row) for row in cursor.fetchall()]
        ti.xcom_push(key="final_results", value=final_results)

    finally:
        cursor.close()
        conn.close()


def generate_summary_report(**context) -> None:
    """
    Task 4: Generate and log a quality summary report.

    SKILL: Airflow task, XCom pull, data aggregation

    Computes statistics across all evaluation results:
    - Average score
    - Pass rate (score >= 0.7)
    - Failed jobs count
    - Best and worst performing prompts

    In a production system, this would:
    - Send an email report (Airflow's EmailOperator)
    - Post to Slack (SlackWebhookOperator)
    - Write to a reporting table in the database
    - Trigger a PagerDuty alert if average score drops below threshold
    """
    ti = context["ti"]
    run_date = context["ds"]

    results = ti.xcom_pull(
        task_ids="wait_for_completions",
        key="final_results"
    )
    prompt_count = ti.xcom_pull(
        task_ids="fetch_active_prompts",
        key="prompt_count"
    )

    if not results:
        logger.info("[generate_summary_report] No results to report")
        return

    # ── COMPUTE STATISTICS ────────────────────────────────────────────
    completed = [r for r in results if r["status"] == "completed"]
    failed = [r for r in results if r["status"] == "failed"]
    scores = [r["score"] for r in completed if r["score"] is not None]

    avg_score = sum(scores) / len(scores) if scores else 0
    pass_rate = len([s for s in scores if s >= 0.7]) / len(scores) if scores else 0
    best_score = max(scores) if scores else 0
    worst_score = min(scores) if scores else 0

    # ── DETERMINE OVERALL HEALTH ──────────────────────────────────────
    if avg_score >= 0.8:
        health = "EXCELLENT"
    elif avg_score >= 0.6:
        health = "GOOD"
    elif avg_score >= 0.4:
        health = "NEEDS ATTENTION"
    else:
        health = "CRITICAL — IMMEDIATE REVIEW REQUIRED"

    # ── LOG REPORT ────────────────────────────────────────────────────
    report = f"""
╔══════════════════════════════════════════════════════════╗
║       PROMPTVAULT NIGHTLY REGRESSION REPORT              ║
║       Run Date: {run_date}                               
╠══════════════════════════════════════════════════════════╣
║  Total Active Prompts:  {prompt_count}
║  Jobs Dispatched:       {len(results)}
║  Completed:             {len(completed)}
║  Failed:                {len(failed)}
╠══════════════════════════════════════════════════════════╣
║  Average Score:         {avg_score:.3f}
║  Pass Rate (≥0.7):      {pass_rate:.1%}
║  Best Score:            {best_score:.3f}
║  Worst Score:           {worst_score:.3f}
╠══════════════════════════════════════════════════════════╣
║  Overall Health:        {health}
╚══════════════════════════════════════════════════════════╝
    """

    logger.info(report)

    # Write summary to database for historical tracking
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    try:
        # Store report summary in a log table if it exists
        # For now, just log it (table created in a future migration)
        logger.info(
            f"[generate_summary_report] "
            f"avg_score={avg_score:.3f} "
            f"pass_rate={pass_rate:.1%} "
            f"health={health}"
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ─────────────────────────────────────────────────────────────────────
# DAG DEFINITION
#
# This is where we wire everything together.
#
# default_args apply to all tasks unless overridden:
#   owner           → who owns this DAG (shows in Airflow UI)
#   retries         → retry failed tasks this many times
#   retry_delay     → wait this long between retries
#   email_on_failure → send email if task fails (we set False for now)
#
# schedule_interval: cron expression
#   "0 0 * * *" = at 00:00 (midnight) every day
#
# catchup=False: if Airflow was down for a week and then restarted,
#   do NOT run the missed runs. Just start from now.
#   catchup=True would run all the missed daily runs — usually unwanted.
#
# max_active_runs=1: only one instance of this DAG runs at a time.
#   Prevents overlap if a run takes longer than 24 hours.
# ─────────────────────────────────────────────────────────────────────
default_args = {
    "owner": "promptvault",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}

with DAG(
    dag_id="nightly_prompt_regression",
    description="Nightly automated evaluation of all active prompts",
    schedule_interval="0 0 * * *",     # Every night at midnight
    start_date=datetime(2026, 1, 1),   # DAG becomes active from this date
    default_args=default_args,
    catchup=False,
    max_active_runs=1,
    tags=["promptvault", "regression", "nightly"],
) as dag:

    # ── TASK DEFINITIONS ─────────────────────────────────────────────
    # PythonOperator wraps a Python function as an Airflow task.
    # task_id   → unique name shown in Airflow UI
    # python_callable → the function to run
    # provide_context → passes Airflow context (ti, ds, etc.) to function
    # ─────────────────────────────────────────────────────────────────

    t1_fetch = PythonOperator(
        task_id="fetch_active_prompts",
        python_callable=fetch_active_prompts,
        provide_context=True,
    )

    t2_dispatch = PythonOperator(
        task_id="dispatch_evaluation_jobs",
        python_callable=dispatch_evaluation_jobs,
        provide_context=True,
    )

    t3_wait = PythonOperator(
        task_id="wait_for_completions",
        python_callable=wait_for_completions,
        provide_context=True,
    )

    t4_report = PythonOperator(
        task_id="generate_summary_report",
        python_callable=generate_summary_report,
        provide_context=True,
    )

    # ── TASK DEPENDENCIES ─────────────────────────────────────────────
    # >> operator sets execution order.
    # t1 >> t2 means: "t2 runs only after t1 succeeds"
    #
    # This is the DAG structure:
    #   fetch_active_prompts
    #          ↓
    #   dispatch_evaluation_jobs
    #          ↓
    #   wait_for_completions
    #          ↓
    #   generate_summary_report
    # ─────────────────────────────────────────────────────────────────
    t1_fetch >> t2_dispatch >> t3_wait >> t4_report