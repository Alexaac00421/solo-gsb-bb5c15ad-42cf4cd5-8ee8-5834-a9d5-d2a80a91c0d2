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
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (batch_id, version_no)
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

-- 每个评估版本生效的监测标准快照（校准只更换标准、不改读数）。
-- 校准前生成的旧版本在该表无记录，查询时回退到文物当前标准（见 init_db 回填）。
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

-- 监测标准校准：工作人员发现限值录错后，以整套新标准重评所见版本全部既有读数，
-- 原子生成新版本（base_version_no → version_no），旧版读数/标准/评估/关闭结论保留。
CREATE TABLE IF NOT EXISTS calibrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    base_version_no INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
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


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _backfill_version_standards(conn):
    """旧库升级：为缺少标准快照的既有版本补拍文物当前标准。

    校准功能上线前的版本都按文物登记表中的标准评估，此处回填为显式快照；
    之后每次生成新版本都会写入当次生效的标准，不再需要补拍。
    """
    missing = conn.execute(
        """SELECT v.id FROM versions v
           WHERE NOT EXISTS (
               SELECT 1 FROM version_standards vs WHERE vs.version_id = v.id)"""
    ).fetchall()
    for row in missing:
        conn.execute(
            """INSERT INTO version_standards(version_id, artifact_id, temp_min,
               temp_max, hum_min, hum_max, sample_interval)
               SELECT ?, a.id, a.temp_min, a.temp_max, a.hum_min, a.hum_max,
                      a.sample_interval
               FROM artifacts a
               WHERE a.batch_id = (SELECT batch_id FROM versions WHERE id = ?)""",
            (row["id"], row["id"]),
        )


def init_db(path):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        _backfill_version_standards(conn)
        conn.commit()
    finally:
        conn.close()
