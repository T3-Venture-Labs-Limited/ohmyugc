import stat

from oh_my_ugc import config, db
from oh_my_ugc.captions import presets


def test_fresh_home_migrates_idempotently(omu_home):
    conn = db.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    db.migrate(conn)  # running twice changes nothing
    db.migrate(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in (
        "settings",
        "brands",
        "products",
        "actors",
        "projects",
        "shots",
        "frames",
        "takes",
        "jobs",
        "media",
        "ledger",
        "variants",
        "cache",
        "calls",
    ):
        assert t in tables
    for sub in ("media", "projects", "catalog"):
        assert (config.home() / sub).exists() or getattr(
            config, {"media": "media_dir", "projects": "projects_dir", "catalog": "user_catalog_dir"}[sub]
        )().exists()


def test_database_file_is_private(omu_home):
    db.connect()
    mode = stat.S_IMODE((omu_home / "omu.db").stat().st_mode)
    assert mode == 0o600


def test_vendored_caption_presets_load():
    assert len(presets.builtin()) >= 15
