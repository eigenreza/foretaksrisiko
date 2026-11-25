"""Thin Databricks entry point: run one pipeline stage through the package CLI.

Use with a spark_python_task or a notebook when a wheel entry point is not wanted, for example:
    python jobs/run_stage.py lakehouse bronze --snapshot 1
"""

from __future__ import annotations

from foretaksrisiko.cli import job_main

if __name__ == "__main__":
    job_main()
