CREATE TABLE IF NOT EXISTS issues (
  issue_id          VARCHAR(64)  NOT NULL,
  repo              VARCHAR(255) NOT NULL,
  code_version      VARCHAR(128) NOT NULL,
  defect_class      VARCHAR(8)   NULL,
  severity          VARCHAR(16)  NOT NULL,
  status            VARCHAR(32)  NOT NULL,
  source_count      INT          NOT NULL DEFAULT 1,
  fingerprint       CHAR(64)     NOT NULL,
  in_scope          TINYINT(1)   NOT NULL DEFAULT 1,
  occurred_at       DATETIME(6)  NOT NULL,
  updated_at        DATETIME(6)  NOT NULL,
  schema_version    INT          NOT NULL DEFAULT 1,
  PRIMARY KEY (issue_id),
  UNIQUE KEY uk_issue_fingerprint (repo, code_version, fingerprint),
  KEY idx_issue_repo_occurred (repo, occurred_at),
  KEY idx_issue_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS alerts (
  alert_ref          VARCHAR(128) NOT NULL,
  issue_id           VARCHAR(64)  NOT NULL,
  source_kind        VARCHAR(24)  NOT NULL,
  rule_id            VARCHAR(128) NOT NULL,
  file_path          VARCHAR(512) NULL,
  line_no            INT          NULL,
  component          VARCHAR(255) NULL,
  component_version  VARCHAR(64)  NULL,
  raw_severity       VARCHAR(16)  NOT NULL,
  snippet_fingerprint CHAR(64)    NOT NULL,
  snippet_ref        VARCHAR(512) NULL,
  observed_at        DATETIME(6)  NOT NULL,
  PRIMARY KEY (alert_ref),
  KEY idx_alert_issue (issue_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS verdicts (
  verdict_id     VARCHAR(64)  NOT NULL,
  issue_id       VARCHAR(64)  NOT NULL,
  conclusion     VARCHAR(16)  NOT NULL,
  confidence     DECIMAL(4,3) NOT NULL,
  taint_path_ref VARCHAR(512) NULL,
  basis_ref      VARCHAR(512) NULL,
  decided_by     VARCHAR(64)  NOT NULL,
  decided_at     DATETIME(6)  NOT NULL,
  is_effective   TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (verdict_id),
  KEY idx_verdict_issue (issue_id, decided_at),
  KEY idx_verdict_effective (issue_id, is_effective)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS proofs (
  proof_id          VARCHAR(64)  NOT NULL,
  issue_id          VARCHAR(64)  NOT NULL,
  test_path         VARCHAR(512) NOT NULL,
  pre_patch_result  VARCHAR(16)  NOT NULL,
  post_patch_result VARCHAR(16)  NOT NULL,
  fingerprint       CHAR(64)     NOT NULL,
  env_snapshot_ref  VARCHAR(512) NOT NULL,
  generated_marker  VARCHAR(128) NOT NULL,
  created_at        DATETIME(6)  NOT NULL,
  PRIMARY KEY (proof_id),
  UNIQUE KEY uk_proof_issue (issue_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS patches (
  patch_id        VARCHAR(64)  NOT NULL,
  issue_id        VARCHAR(64)  NOT NULL,
  proof_id        VARCHAR(64)  NOT NULL,
  branch          VARCHAR(255) NOT NULL,
  diff_ref        VARCHAR(512) NOT NULL,
  lines_changed   INT          NOT NULL,
  files_changed   INT          NOT NULL,
  fix_paradigm    VARCHAR(32)  NOT NULL,
  patch_strength  DECIMAL(4,3) NOT NULL,
  quotas_ok       TINYINT(1)   NOT NULL DEFAULT 0,
  created_at      DATETIME(6)  NOT NULL,
  PRIMARY KEY (patch_id),
  UNIQUE KEY uk_patch_issue (issue_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_findings (
  patch_id     VARCHAR(64)  NOT NULL,
  rule_id      VARCHAR(8)   NOT NULL,
  threshold    VARCHAR(64)  NOT NULL,
  hit_location VARCHAR(512) NOT NULL,
  verdict      VARCHAR(16)  NOT NULL,
  reason_ref   VARCHAR(512) NULL,
  PRIMARY KEY (patch_id, rule_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS gate_results (
  gate_result_id     VARCHAR(64)  NOT NULL,
  patch_id           VARCHAR(64)  NOT NULL,
  gate_run_ref       VARCHAR(255) NOT NULL,
  red_green_paired   TINYINT(1)   NOT NULL DEFAULT 0,
  regression_zero_fail TINYINT(1) NOT NULL DEFAULT 0,
  coverage_delta_pp  DECIMAL(6,3) NOT NULL DEFAULT 0,
  rescan_new_alerts  INT          NOT NULL DEFAULT 0,
  outcome            VARCHAR(16)  NOT NULL,
  evidence_missing   TINYINT(1)   NOT NULL DEFAULT 0,
  observed_at        DATETIME(6)  NOT NULL,
  PRIMARY KEY (gate_result_id),
  UNIQUE KEY uk_gate_run_ref (gate_run_ref),
  KEY idx_gate_patch (patch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dispositions (
  disposition_id VARCHAR(64)  NOT NULL,
  issue_id       VARCHAR(64)  NOT NULL,
  level          VARCHAR(4)   NOT NULL,
  action         VARCHAR(64)  NOT NULL,
  evidence_ref   VARCHAR(512) NOT NULL,
  reason_code    VARCHAR(64)  NOT NULL,
  decided_at     DATETIME(6)  NOT NULL,
  PRIMARY KEY (disposition_id),
  UNIQUE KEY uk_disposition_issue (issue_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS runs (
  run_id         VARCHAR(64)  NOT NULL,
  issue_id       VARCHAR(64)  NOT NULL,
  started_at     DATETIME(6)  NOT NULL,
  ended_at       DATETIME(6)  NULL,
  terminal_state VARCHAR(24)  NULL,
  deadline_at    DATETIME(6)  NOT NULL,
  PRIMARY KEY (run_id),
  KEY idx_run_issue (issue_id),
  KEY idx_run_terminal (terminal_state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS run_steps (
  run_id       VARCHAR(64)  NOT NULL,
  kind         VARCHAR(16)  NOT NULL,
  status       VARCHAR(16)  NOT NULL,
  started_at   DATETIME(6)  NULL,
  ended_at     DATETIME(6)  NULL,
  evidence_ref VARCHAR(512) NULL,
  detail_ref   VARCHAR(512) NULL,
  PRIMARY KEY (run_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS events (
  event_id       VARCHAR(80)  NOT NULL,
  run_id         VARCHAR(64)  NOT NULL,
  seq            INT          NOT NULL,
  event_type     VARCHAR(24)  NOT NULL,
  occurred_at    DATETIME(6)  NOT NULL,
  actor          VARCHAR(64)  NOT NULL,
  step           VARCHAR(16)  NULL,
  payload_ref    VARCHAR(512) NULL,
  prev_hash      CHAR(64)     NOT NULL,
  self_hash      CHAR(64)     NOT NULL,
  schema_version INT          NOT NULL DEFAULT 1,
  PRIMARY KEY (event_id),
  UNIQUE KEY uk_event_run_seq (run_id, seq),
  KEY idx_event_type_time (event_type, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS metrics (
  metric_id          VARCHAR(4)   NOT NULL,
  stage_tier         VARCHAR(16)  NOT NULL,
  window_label       VARCHAR(64)  NOT NULL,
  definition_version VARCHAR(16)  NOT NULL,
  value              DECIMAL(12,4) NULL,
  source_ref         VARCHAR(512) NOT NULL,
  computed_at        DATETIME(6)  NOT NULL,
  computable         TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (metric_id, stage_tier, window_label)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS eval_cases (
  case_id      VARCHAR(16)  NOT NULL,
  category     VARCHAR(16)  NOT NULL,
  rule_id      VARCHAR(128) NOT NULL,
  severity     VARCHAR(16)  NOT NULL,
  location_ref VARCHAR(512) NOT NULL,
  ground_truth_ref VARCHAR(512) NOT NULL,
  content_digest CHAR(64)   NOT NULL,
  PRIMARY KEY (case_id),
  KEY idx_eval_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS circuit_states (
  defect_class  VARCHAR(8)   NOT NULL,
  fail_streak   INT          NOT NULL DEFAULT 0,
  state         VARCHAR(8)   NOT NULL,
  opened_at     DATETIME(6)  NULL,
  updated_at    DATETIME(6)  NOT NULL,
  PRIMARY KEY (defect_class)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS outbox (
  task_key     VARCHAR(128) NOT NULL,
  task_type    VARCHAR(64)  NOT NULL,
  payload_ref  VARCHAR(512) NOT NULL,
  status       VARCHAR(16)  NOT NULL DEFAULT 'PENDING',
  created_at   DATETIME(6)  NOT NULL,
  updated_at   DATETIME(6)  NOT NULL,
  PRIMARY KEY (task_key),
  KEY idx_outbox_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;