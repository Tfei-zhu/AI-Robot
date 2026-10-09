"""按认证账户保存完整尝试与最终报告，不依赖短期 trace 缓冲。"""
import json
import sqlite3
import threading
from pathlib import Path


class GoTaskStore:
    def __init__(self, path: str):
        self.path = path
        self._connection = None
        self._lock = threading.RLock()

    def _db(self):
        # 导入模块不产生数据库副作用，首次真正读写时建表。
        if self._connection is None:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path, check_same_thread=False)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("CREATE TABLE IF NOT EXISTS go_tasks "
                                     "(run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, result TEXT NOT NULL)")
        return self._connection

    def save(self, run_id: str, owner: str, result: dict):
        with self._lock:
            db = self._db()
            existing = db.execute("SELECT owner FROM go_tasks WHERE run_id=?", (run_id,)).fetchone()
            if existing and existing[0] != owner:
                raise ValueError("任务归属不一致")
            db.execute("INSERT INTO go_tasks VALUES (?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET result=excluded.result",
                       (run_id, owner, json.dumps(result, ensure_ascii=False)))
            db.commit()

    def get(self, run_id: str, owner: str):
        with self._lock:
            row = self._db().execute("SELECT result FROM go_tasks WHERE run_id=? AND owner=?", (run_id, owner)).fetchone()
            return json.loads(row[0]) if row else None

    def close(self):
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
