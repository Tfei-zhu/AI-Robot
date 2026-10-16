"""原始历史、工具原文和摘要的账户/会话隔离存储。"""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


class ContextStore:
    def __init__(self,path):
        self.path=str(path);self.connection=None;self.lock=threading.RLock()

    def db(self):
        if self.connection is None:
            if self.path!=":memory:":Path(self.path).parent.mkdir(parents=True,exist_ok=True)
            self.connection=sqlite3.connect(self.path,check_same_thread=False)
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.executescript('''
CREATE TABLE IF NOT EXISTS context_turns(owner TEXT,sid TEXT,turn INTEGER,run_id TEXT,user TEXT,assistant TEXT,created REAL,PRIMARY KEY(owner,sid,turn),UNIQUE(owner,sid,run_id));
CREATE TABLE IF NOT EXISTS context_summaries(owner TEXT,sid TEXT,version INTEGER,covered INTEGER,payload TEXT,PRIMARY KEY(owner,sid));
CREATE TABLE IF NOT EXISTS context_summary_versions(owner TEXT,sid TEXT,version INTEGER,payload TEXT,PRIMARY KEY(owner,sid,version));
INSERT OR IGNORE INTO context_summary_versions SELECT owner,sid,version,payload FROM context_summaries;
CREATE TABLE IF NOT EXISTS context_results(id TEXT PRIMARY KEY,owner TEXT,sid TEXT,run_id TEXT,payload TEXT,created REAL);
CREATE TABLE IF NOT EXISTS context_runs(run_id TEXT PRIMARY KEY,owner TEXT,sid TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS context_imports(owner TEXT,sid TEXT,PRIMARY KEY(owner,sid));
CREATE TABLE IF NOT EXISTS context_evidence(owner TEXT,sid TEXT,id TEXT,payload TEXT,PRIMARY KEY(owner,sid,id));
CREATE TABLE IF NOT EXISTS context_searches(owner TEXT,sid TEXT,key TEXT,payload TEXT,created REAL,PRIMARY KEY(owner,sid,key));
''')
        return self.connection

    def turns(self,owner,sid):
        with self.lock:
            rows=self.db().execute("SELECT turn,run_id,user,assistant FROM context_turns WHERE owner=? AND sid=? ORDER BY turn",(owner,sid)).fetchall()
            return [dict(zip(("turn","run_id","user","assistant"),r)) for r in rows]

    def summary(self,owner,sid):
        with self.lock:
            row=self.db().execute("SELECT payload FROM context_summaries WHERE owner=? AND sid=?",(owner,sid)).fetchone()
            return json.loads(row[0]) if row else None

    def summary_versions(self,owner,sid):
        with self.lock:
            rows=self.db().execute("SELECT payload FROM context_summary_versions WHERE owner=? AND sid=? ORDER BY version",(owner,sid)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def commit(self,owner,sid,run_id,user,assistant,summary=None,expected_version=None):
        with self.lock:
            db=self.db()
            with db:
                old=db.execute("SELECT turn FROM context_turns WHERE owner=? AND sid=? AND run_id=?",(owner,sid,run_id)).fetchone()
                if old:return old[0]
                n=db.execute("SELECT COALESCE(MAX(turn),0) FROM context_turns WHERE owner=? AND sid=?",(owner,sid)).fetchone()[0]
                if summary is not None:
                    from app.context.contracts import SessionSummary
                    item=SessionSummary.model_validate(summary)
                    previous=db.execute("SELECT version,covered FROM context_summaries WHERE owner=? AND sid=?",(owner,sid)).fetchone()
                    version=previous[0] if previous else 0
                    if version!=expected_version or item.version!=version+1 or item.covered_until_turn>n:
                        raise ValueError("摘要版本或覆盖轮次冲突")
                    if previous and item.covered_until_turn<previous[1]:raise ValueError("摘要覆盖范围不能倒退")
                    for key in ("goal","constraints","corrections","confirmed_facts","decisions","completed","pending"):
                        for fact in getattr(item,key):
                            if any(t<1 or t>item.covered_until_turn for t in fact.source_turns):raise ValueError("摘要来源轮次无效")
                    if item.evidence_refs:
                        known={r[0] for r in db.execute("SELECT id FROM context_results WHERE owner=? AND sid=? UNION SELECT id FROM context_evidence WHERE owner=? AND sid=?",(owner,sid,owner,sid))}
                        if not set(item.evidence_refs)<=known:raise ValueError("摘要引用未知证据")
                    db.execute("INSERT INTO context_summaries VALUES(?,?,?,?,?) ON CONFLICT(owner,sid) DO UPDATE SET version=excluded.version,covered=excluded.covered,payload=excluded.payload",
                               (owner,sid,item.version,item.covered_until_turn,json.dumps(item.model_dump(),ensure_ascii=False)))
                    # 与原始轮次同一事务归档每个有效版本，便于重放和回溯纠正关系。
                    db.execute("INSERT INTO context_summary_versions VALUES(?,?,?,?)",
                               (owner,sid,item.version,json.dumps(item.model_dump(),ensure_ascii=False)))
                db.execute("INSERT INTO context_turns VALUES(?,?,?,?,?,?,?)",(owner,sid,n+1,run_id,user,assistant,time.time()))
                return n+1

    def import_legacy(self,owner,sid,messages):
        with self.lock:
            db=self.db()
            with db:
                if db.execute("SELECT 1 FROM context_imports WHERE owner=? AND sid=?",(owner,sid)).fetchone():return
                if not self.turns(owner,sid):
                    for i in range(0,len(messages)-1,2):
                        # 整次导入在同一事务，避免中途失败后只留下部分旧历史。
                        db.execute("INSERT INTO context_turns VALUES(?,?,?,?,?,?,?)",
                                   (owner,sid,i//2+1,f"legacy-{i//2}",str(messages[i].content),str(messages[i+1].content),time.time()))
                db.execute("INSERT INTO context_imports VALUES(?,?)",(owner,sid))

    def save_result(self,owner,sid,run_id,payload):
        result_id=uuid.uuid4().hex
        with self.lock,self.db():
            self.db().execute("INSERT INTO context_results VALUES(?,?,?,?,?,?)",(result_id,owner,sid,run_id,json.dumps(payload,ensure_ascii=False),time.time()))
        return result_id

    def result(self,owner,sid,result_id):
        with self.lock:
            row=self.db().execute("SELECT payload FROM context_results WHERE owner=? AND sid=? AND id=?",(owner,sid,result_id)).fetchone()
            return json.loads(row[0]) if row else None

    def save_run(self,owner,sid,run_id,payload):
        with self.lock,self.db():
            self.db().execute("INSERT INTO context_runs VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload WHERE owner=excluded.owner AND sid=excluded.sid",
                              (run_id,owner,sid,json.dumps(payload,ensure_ascii=False)))

    def clear(self,owner,sid):
        with self.lock,self.db():
            for table in ("context_turns","context_summaries","context_summary_versions","context_results","context_runs","context_imports","context_evidence","context_searches"):
                self.db().execute(f"DELETE FROM {table} WHERE owner=? AND sid=?",(owner,sid))

    def evidence(self,owner,sid,evidence_id,payload=None):
        with self.lock,self.db():
            if payload is not None:
                self.db().execute("INSERT INTO context_evidence VALUES(?,?,?,?) ON CONFLICT(owner,sid,id) DO UPDATE SET payload=excluded.payload",
                                  (owner,sid,evidence_id,json.dumps(payload,ensure_ascii=False)))
            row=self.db().execute("SELECT payload FROM context_evidence WHERE owner=? AND sid=? AND id=?",(owner,sid,evidence_id)).fetchone()
            return json.loads(row[0]) if row else None

    def search_cache(self,owner,sid,key,payload=None,ttl=600):
        with self.lock,self.db():
            if payload is not None:
                self.db().execute("INSERT INTO context_searches VALUES(?,?,?,?,?) ON CONFLICT(owner,sid,key) DO UPDATE SET payload=excluded.payload,created=excluded.created",
                                  (owner,sid,key,json.dumps(payload,ensure_ascii=False),time.time()))
            row=self.db().execute("SELECT payload,created FROM context_searches WHERE owner=? AND sid=? AND key=?",(owner,sid,key)).fetchone()
            return json.loads(row[0]) if row and time.time()-row[1]<=ttl else None

    def readable_refs(self,owner,sid):
        with self.lock:
            evidence=[r[0] for r in self.db().execute("SELECT id FROM context_evidence WHERE owner=? AND sid=? ORDER BY rowid DESC LIMIT 20",(owner,sid))]
            results=[r[0] for r in self.db().execute("SELECT id,payload FROM context_results WHERE owner=? AND sid=? ORDER BY rowid DESC LIMIT 40",(owner,sid))
                     if json.loads(r[1]).get("tool")!="summary_candidate"]
            return list(dict.fromkeys([*evidence,*results]))[:20]

    def close(self):
        with self.lock:
            if self.connection is not None:self.connection.close();self.connection=None


_stores={}
_stores_lock=threading.RLock()


def get_store():
    from app.config import settings
    path=settings.context_store_path
    if path!=":memory:" and not Path(path).is_absolute():path=str(ROOT/path)
    with _stores_lock:
        return _stores.setdefault(path,ContextStore(path))


def close_stores():
    with _stores_lock:
        for item in _stores.values():item.close()
        _stores.clear()
