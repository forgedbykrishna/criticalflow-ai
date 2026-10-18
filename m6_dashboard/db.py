
import os

from pathlib import Path

import pandas as pd
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv


# --------------------------------------------------
# 1. Load environment variables
# --------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
env_path = ROOT_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()


# --------------------------------------------------
# 2. Connect to PostgreSQL
# --------------------------------------------------

def get_database_url() -> str:
    """Resolve database URL from environment or construct default local connection string."""
    url = (os.getenv("DASHBOARD_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if url:
        return url

    # Fallback to local PostgreSQL service using environment variables with defaults
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "criticalflow")

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_connection():
    """Connect to PostgreSQL (supports both local Docker and hosted Neon DB)."""

    database_url = get_database_url()

    connect_kwargs = {"connect_timeout": 10}

    # Respect explicit sslmode in connection URL if present.
    # Otherwise use DB_SSLMODE / PGSSLMODE or default to "prefer"
    # (negotiates SSL with Neon DB, cleanly falls back to non-SSL on local Docker postgres).
    if "sslmode=" not in database_url:
        sslmode = os.getenv("DB_SSLMODE") or os.getenv("PGSSLMODE") or "prefer"
        connect_kwargs["sslmode"] = sslmode

    return psycopg.connect(
        database_url,
        **connect_kwargs,
    )


# --------------------------------------------------
# 3. Load incidents from the database
# --------------------------------------------------

def load_incidents():
    """Fetch incident records into a Pandas DataFrame."""

    query = """
        SELECT *
        FROM incident_overview
        ORDER BY event_time DESC;
    """

    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
        return pd.DataFrame(rows)
    except Exception as exc:
        mock_path = Path(__file__).resolve().parent / "mock_data" / "incidents.json"
        if mock_path.exists():
            import json
            with open(mock_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return pd.DataFrame(data)
        raise exc


# --------------------------------------------------
# 4. Test connection and display a clean summary
# --------------------------------------------------

if __name__ == "__main__":

    try:
        df = load_incidents()

        print("\n" + "=" * 65)
        print("             NEON POSTGRESQL DASHBOARD")
        print("=" * 65)

        print("\nConnection Status : SUCCESS")
        print(f"Total Incidents   : {len(df):,}")
        print(f"Total Columns     : {len(df.columns)}")

        print("\nAvailable Columns:")
        for column in df.columns:
            print(f"  - {column}")

        if df.empty:
            print("\nNo incidents found in incident_overview.")

        else:
            preview_columns = [
                "incident_id",
                "event_type",
                "system",
                "job_name",
                "severity",
                "anomaly_score",
                "incident_status",
            ]

            available_columns = [
                column
                for column in preview_columns
                if column in df.columns
            ]

            print("\nRecent Incidents:")
            print("-" * 65)

            print(
                df[available_columns]
                .head(10)
                .to_string(index=False)
            )

        print("\n" + "=" * 65)
        print("Database test completed successfully.")
        print("=" * 65 + "\n")

    except Exception as error:
        print("\nDatabase connection or query failed.")
        print(f"Error: {error}")
