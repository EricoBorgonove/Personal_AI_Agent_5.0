from .calendar_repository import LocalCalendarProvider
from .obligations_repository import ObligationsRepository
from .finance_repository import FinanceRepository
from .sqlite import rows, savepoint
class Repository:
    def __init__(self,db): self.db=db; self.calendar=LocalCalendarProvider(db); self.finance=FinanceRepository(db); self.obligations=ObligationsRepository(db)
    def atomic(self): return savepoint(self.db)
    def notify(self,to,text): self.db.execute('INSERT INTO outbox(recipient,text) VALUES (?,?)',(to,text))
    def requests(self,sender=None):
        return rows(self.db,'SELECT * FROM requests WHERE sender=? ORDER BY id DESC LIMIT 20',(sender,)) if sender is not None else rows(self.db,'SELECT * FROM requests ORDER BY id DESC LIMIT 20')
    def duplicate(self,sender,subject,slot):
        return self.db.execute("SELECT id FROM requests WHERE sender=? AND subject=? AND slot=? AND status IN ('PENDENTE','CONTRAPROPOSTA','ACEITA','CONFIRMADA')",(sender,subject,slot)).fetchone()
    def create_request(self,sender,name,subject,slot):
        i=self.db.execute("INSERT INTO requests(sender,name,subject,slot,status) VALUES (?,?,?,?,'PENDENTE')",(sender,name,subject,slot)).lastrowid
        self.db.execute('INSERT INTO transitions(request_id,actor,status,slot) VALUES (?,?,?,?)',(i,sender,'PENDENTE',slot))
        return i
    def request(self,i): return self.db.execute('SELECT * FROM requests WHERE id=?',(i,)).fetchone()
    def conflict(self,slot,i): return self.db.execute("SELECT 1 FROM requests WHERE slot=? AND status='CONFIRMADA' AND id<>?",(slot,i)).fetchone()
    def change(self,i,actor,state,slot):
        self.db.execute('UPDATE requests SET status=?,slot=? WHERE id=?',(state,slot,i))
        self.db.execute('INSERT INTO transitions(request_id,actor,status,slot) VALUES (?,?,?,?)',(i,actor,state,slot))
    def note(self,sender,text): self.db.execute('INSERT INTO notes(sender,text) VALUES (?,?)',(sender,text))
    def notes(self): return rows(self.db,'SELECT * FROM notes ORDER BY id DESC LIMIT 20')
    def create_task(self,text): return self.db.execute('INSERT INTO tasks(text) VALUES (?)',(text,)).lastrowid
    def tasks(self): return rows(self.db,'SELECT * FROM tasks WHERE done=0 ORDER BY id LIMIT 30')
    def finish_task(self,i): return self.db.execute('UPDATE tasks SET done=1 WHERE id=?',(i,)).rowcount
    def remember(self,text): self.db.execute('INSERT INTO memories(text) VALUES (?)',(text,))
    def memories(self,query): return rows(self.db,'SELECT * FROM memories WHERE text LIKE ? ORDER BY id DESC LIMIT 20',('%'+query+'%',))
    def agenda(self): return rows(self.db,"SELECT id,name,subject,slot FROM requests WHERE status='CONFIRMADA' ORDER BY slot LIMIT 50")
    def seen(self,sender,event): return not self.db.execute('INSERT OR IGNORE INTO seen VALUES (?)',(sender+':'+event,)).rowcount
    def mark_presentation(self, identifiers, role):
        first = True
        for identifier in identifiers:
            inserted = self.db.execute(
                'INSERT OR IGNORE INTO presentations(sender, role) VALUES (?, ?)', (identifier, role)
            ).rowcount
            if not inserted:
                first = False
        return first
    def history(self,sender): return rows(self.db,'SELECT role,content FROM messages WHERE sender=? ORDER BY id DESC LIMIT 12',(sender,))[::-1]
    def record(self,sender,text,answer): self.db.executemany('INSERT INTO messages(sender,role,content) VALUES (?,?,?)',[(sender,'user',text),(sender,'assistant',answer)])
    def pending(self): return rows(self.db,'SELECT * FROM outbox WHERE sent=0 ORDER BY id')
    def delivered(self,i): self.db.execute('UPDATE outbox SET sent=1 WHERE id=?',(i,))
