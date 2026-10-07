"""SQLite 持久化层：连接与表结构。"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    UNIQUE (batch_id, seq)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    temp_min REAL NOT NULL,
    temp_max REAL NOT NULL,
    hum_min REAL NOT NULL,
    hum_max REAL NOT NULL,
    sample_interval INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'readings',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, version_no)
);

-- 每个评估版本所依据的各文物监测标准快照（温湿度上下限 + 采样间隔）。
-- 读数提交版本照录当时文物标准；标准校准版本中被校准文物使用新标准，
-- 其余文物沿用所校准（所见）版本的标准。旧版标准始终随快照可查。
CREATE TABLE IF NOT EXISTS version_standards (
    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    temp_min REAL NOT NULL,
    temp_max REAL NOT NULL,
    hum_min REAL NOT NULL,
    hum_max REAL NOT NULL,
    sample_interval INTEGER NOT NULL,
    PRIMARY KEY (version_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    node_id INTEGER NOT NULL REFERENCES nodes(id),
    ts TEXT NOT NULL,
    temperature REAL NOT NULL,
    humidity REAL NOT NULL,
    corrected_from INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    metric TEXT NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    reading_count INTEGER NOT NULL,
    min_value REAL NOT NULL,
    max_value REAL NOT NULL,
    limit_lo REAL NOT NULL,
    limit_hi REAL NOT NULL,
    nodes TEXT NOT NULL,
    max_deviation REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    close_note TEXT,
    close_evidence TEXT,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    expected_interval INTEGER NOT NULL,
    actual_interval REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    package_id TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, package_id)
);

CREATE TABLE IF NOT EXISTS handovers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    prev_node_id INTEGER NOT NULL REFERENCES nodes(id),
    next_node_id INTEGER NOT NULL REFERENCES nodes(id),
    handover_ts TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    result TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    evidence_no TEXT NOT NULL DEFAULT '',
    items_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 监测标准校准记录：工作人员发现某文物监测标准录错后，以整套新标准重评
-- 所见版本的全部既有读数，原子生成一个 kind='calibration' 的新版本。
-- old_* 保存校准前（所见版本中该文物）的标准，新事件一律重新开放。
CREATE TABLE IF NOT EXISTS calibrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    seen_version_no INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    old_temp_min REAL NOT NULL,
    old_temp_max REAL NOT NULL,
    old_hum_min REAL NOT NULL,
    old_hum_max REAL NOT NULL,
    old_sample_interval INTEGER NOT NULL,
    new_temp_min REAL NOT NULL,
    new_temp_max REAL NOT NULL,
    new_hum_min REAL NOT NULL,
    new_hum_max REAL NOT NULL,
    new_sample_interval INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_readings_version ON readings(version_id, artifact_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_version ON events(version_id, status);
CREATE INDEX IF NOT EXISTS idx_gaps_version ON gaps(version_id);
CREATE INDEX IF NOT EXISTS idx_packages_batch ON packages(batch_id);
CREATE INDEX IF NOT EXISTS idx_handovers_batch ON handovers(batch_id);
CREATE INDEX IF NOT EXISTS idx_version_standards_version ON version_standards(version_id);
CREATE INDEX IF NOT EXISTS idx_calibrations_batch ON calibrations(batch_id);
"""

# 旧库迁移：补齐标准校准所需列（全新库的 versions 建表语句已含 kind 列）。
MIGRATIONS = (
    (
        "versions", "kind",
        "ALTER TABLE versions ADD COLUMN kind TEXT NOT NULL DEFAULT 'readings'",
    ),
)


def _migrate(conn):
    for table, column, ddl in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(ddl)


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
