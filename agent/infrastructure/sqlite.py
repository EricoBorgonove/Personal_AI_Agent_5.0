import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

def rows(db, sql, args=()): return [dict(r) for r in db.execute(sql,args)]

class SQLiteUnitOfWork:
    def __init__(self,path):
        self.path=path
        with self.connection() as d, d:
            d.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf8'))
    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path,timeout=30)) as d:
            d.row_factory=sqlite3.Row
            d.execute("PRAGMA foreign_keys=ON")
            yield d
    @contextmanager
    def transaction(self):
        with self.connection() as d, d:
            d.execute('BEGIN IMMEDIATE')
            yield d
@contextmanager
def savepoint(d):
    d.execute('SAVEPOINT tool')
    try: yield
    except Exception:
        d.execute('ROLLBACK TO tool'); raise
    finally: d.execute('RELEASE tool')
