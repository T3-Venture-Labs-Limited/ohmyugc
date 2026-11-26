"""SQLite storage: settings, brands, products, actors, projects, shots, jobs, media and the ledger."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from oh_my_ugc import config

MIGRATIONS: list[str] = [
    # 1 — everything v1 needs
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE brands (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        voice_tone TEXT NOT NULL DEFAULT '', audience TEXT NOT NULL DEFAULT '',
        must_mention TEXT NOT NULL DEFAULT '', avoid_claims TEXT NOT NULL DEFAULT '',
        offer TEXT NOT NULL DEFAULT '', cta TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '',
        logo TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE products (
        id TEXT PRIMARY KEY, brand_id TEXT NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
        name TEXT NOT NULL, facts TEXT NOT NULL DEFAULT '', label_text TEXT NOT NULL DEFAULT '',
        photos TEXT NOT NULL DEFAULT '[]', primary_photo TEXT, cutout TEXT, cutout_custom INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE actors (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        refs TEXT NOT NULL DEFAULT '[]', candidates TEXT NOT NULL DEFAULT '[]',
        voice_provider TEXT NOT NULL DEFAULT '', voice_id TEXT NOT NULL DEFAULT '', voice_sample TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE projects (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        brand_id TEXT, product_id TEXT, actor_id TEXT,
        format TEXT NOT NULL DEFAULT 'talking_head', target_seconds REAL NOT NULL DEFAULT 30,
        aspect TEXT NOT NULL DEFAULT '9:16', platform TEXT NOT NULL DEFAULT 'tiktok',
        voice_mode TEXT NOT NULL DEFAULT 'voiceover', brief TEXT NOT NULL DEFAULT '',
        script TEXT NOT NULL DEFAULT '', models TEXT NOT NULL DEFAULT '{}',
        budget REAL, caption_style TEXT NOT NULL DEFAULT 'punch', caption_on INTEGER NOT NULL DEFAULT 1,
        music TEXT, music_volume REAL NOT NULL DEFAULT 0.18,
        end_card TEXT NOT NULL DEFAULT '{}', output_height INTEGER NOT NULL DEFAULT 1920,
        crossfade REAL NOT NULL DEFAULT 0, final_resolution TEXT NOT NULL DEFAULT '720p', stage TEXT NOT NULL DEFAULT 'brief',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE shots (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        variant_id TEXT, position INTEGER NOT NULL DEFAULT 0,
        purpose TEXT NOT NULL DEFAULT 'other', type TEXT NOT NULL DEFAULT 'talking',
        framing TEXT NOT NULL DEFAULT '', setting TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '',
        line TEXT NOT NULL DEFAULT '', onscreen TEXT NOT NULL DEFAULT '', duration REAL NOT NULL DEFAULT 4,
        approved INTEGER NOT NULL DEFAULT 0, frame TEXT, frame_basis TEXT, frame_stale INTEGER NOT NULL DEFAULT 0,
        frame_drift TEXT, end_frame TEXT, block INTEGER, voice_mode TEXT,
        motion TEXT NOT NULL DEFAULT 'push_in', background TEXT NOT NULL DEFAULT 'blur',
        chosen_take TEXT, words TEXT NOT NULL DEFAULT '[]', audio TEXT, text_card INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX shots_project ON shots(project_id, variant_id, position);
    CREATE TABLE frames (
        id TEXT PRIMARY KEY, shot_id TEXT NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
        media TEXT NOT NULL, basis TEXT, note TEXT NOT NULL DEFAULT '', drift TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE takes (
        id TEXT PRIMARY KEY, shot_id TEXT NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
        media TEXT NOT NULL, quality TEXT NOT NULL, take INTEGER NOT NULL DEFAULT 0, prompt TEXT NOT NULL DEFAULT '',
        drift TEXT, trim_start REAL NOT NULL DEFAULT 0, trim_end REAL, duration REAL,
        has_audio INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE variants (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name TEXT NOT NULL, hook TEXT NOT NULL DEFAULT '', kept INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
    );
    CREATE TABLE jobs (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, project_id TEXT, shot_id TEXT,
        status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}',
        result TEXT NOT NULL DEFAULT '{}', error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        started_at TEXT
    );
    CREATE TABLE calls (
        key TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, provider_job_id TEXT,
        status TEXT NOT NULL, outputs TEXT NOT NULL DEFAULT '[]', meta TEXT NOT NULL DEFAULT '{}',
        error TEXT, estimate REAL, actual REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE media (
        hash TEXT PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE cache (
        key TEXT PRIMARY KEY, outputs TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', cost REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, project_id TEXT, job_id TEXT, step TEXT NOT NULL,
        provider TEXT NOT NULL, model TEXT NOT NULL, units TEXT NOT NULL DEFAULT '', estimated REAL NOT NULL DEFAULT 0,
        actual REAL, computed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ok'
    );
    CREATE TABLE reservations (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, amount REAL NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE price_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched_at REAL NOT NULL);
    """,
]

JSON_FIELDS = {
    "photos",
    "refs",
    "candidates",
    "models",
    "end_card",
    "payload",
    "result",
    "outputs",
    "meta",
    "words",
    "frame_drift",
    "drift",
}

_local = threading.local()
_init_lock = threading.Lock()
_initialized: set[str] = set()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def db_path() -> str:
    return str(config.home() / "omu.db")


def connect() -> sqlite3.Connection:
    """One connection per thread, created and migrated on first use."""
    path = db_path()
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == path:
        return conn
    first = not os.path.exists(path)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    if first:
        try:
            os.chmod(path, 0o600)  # holds API keys
        except OSError:
            pass
    with _init_lock:
        if path not in _initialized:
            migrate(conn)
            _initialized.add(path)
    _local.conn, _local.path = conn, path
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript("BEGIN;" + script + f"PRAGMA user_version={i};COMMIT;")


def reset_for_tests() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _initialized.clear()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """A write transaction that takes the lock up front (BEGIN IMMEDIATE)."""
    conn = connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for key in JSON_FIELDS & out.keys():
        if isinstance(out[key], str):
            try:
                out[key] = json.loads(out[key])
            except ValueError:
                pass
    return out


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    return _decode(connect().execute(sql, params).fetchone())


def many(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    return [_decode(r) for r in connect().execute(sql, params).fetchall()]  # type: ignore[misc]


def run(sql: str, params: tuple | list = ()) -> None:
    connect().execute(sql, params)


def _enc(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def insert(table: str, values: dict[str, Any]) -> str:
    values = (
        {"id": new_id(), **values}
        if "id" not in values and table not in ("media", "cache", "calls", "ledger")
        else values
    )
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    connect().execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", [_enc(v) for v in values.values()])
    if table == "ledger":
        return str(connect().execute("SELECT last_insert_rowid()").fetchone()[0])
    return values.get("id") or values.get("key") or values.get("hash")  # type: ignore[return-value]


def update(table: str, row_id: str, values: dict[str, Any], key: str = "id") -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = ?" for k in values)
    connect().execute(
        f"UPDATE {table} SET {sets} WHERE {key} = ?", [*[_enc(v) for v in values.values()], row_id]
    )


def delete(table: str, row_id: str, key: str = "id") -> None:
    connect().execute(f"DELETE FROM {table} WHERE {key} = ?", (row_id,))


# ── settings ─────────────────────────────────────────────────────────────────


def get_setting(key: str) -> str:
    row = connect().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def set_setting(key: str, value: str) -> None:
    if value == "":
        connect().execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        connect().execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
