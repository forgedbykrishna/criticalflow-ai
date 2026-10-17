CREATE TABLE IF NOT EXISTS incidents (
    id                        BIGSERIAL PRIMARY KEY,
    incident_id               TEXT        NOT NULL UNIQUE,
    schema_version            TEXT        NOT NULL,
    event_ts                  TIMESTAMPTZ NOT NULL,
    system_id                 TEXT        NOT NULL,
    subsystem                 TEXT        NOT NULL,
    job_name                  TEXT        NOT NULL,
    job_id                    TEXT        NOT NULL,
    step_name                 TEXT        NOT NULL,
    completion_status         TEXT        NOT NULL CHECK (completion_status IN ('CC','ABEND','JCL_ERROR')),
    return_code               INTEGER     CHECK (return_code BETWEEN 0 AND 4095),
    abend_code                TEXT,
    primary_message_id        TEXT,
    cpu_utilization_pct       NUMERIC(5,2) CHECK (cpu_utilization_pct BETWEEN 0 AND 100),
    error_rate_pct            NUMERIC(5,2) CHECK (error_rate_pct BETWEEN 0 AND 100),
    transaction_volume_per_hr INTEGER     CHECK (transaction_volume_per_hr >= 0),
    recent_deployment_flag    BOOLEAN     NOT NULL DEFAULT FALSE,
    raw_log_snippet           TEXT        NOT NULL,
    ingested_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_score                NUMERIC(5,4),
    llm_explanation           TEXT,
    llm_remediation           TEXT,
    triage_status             TEXT        NOT NULL DEFAULT 'NEW',
    CONSTRAINT ck_cc_fields    CHECK (completion_status <> 'CC'    OR (return_code IS NOT NULL AND abend_code IS NULL)),
    CONSTRAINT ck_abend_fields CHECK (completion_status <> 'ABEND' OR (return_code IS NULL AND abend_code IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_incidents_event_ts ON incidents (event_ts DESC);
CREATE INDEX IF NOT EXISTS ix_incidents_system   ON incidents (system_id, subsystem, event_ts DESC);
CREATE INDEX IF NOT EXISTS ix_incidents_risk     ON incidents (risk_score DESC NULLS LAST);
