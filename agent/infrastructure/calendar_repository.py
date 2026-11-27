from .sqlite import rows
class LocalCalendarProvider:
    def __init__(self,db): self.db=db
    def list_events(self,start,end):
        return rows(self.db,"SELECT * FROM calendar_events WHERE status='ativo' AND start<? AND end>? ORDER BY start,id",(end,start))
    def search_events(self, term, start):
        return rows(self.db, """SELECT id,title,start,end,revision FROM calendar_events
            WHERE status='ativo' AND request_id IS NULL AND start>=?
            AND instr(lower(title),lower(?))>0 ORDER BY start,id LIMIT 10""", (start, term))
    def conflicts(self,start,end,exclude=None):
        return [e for e in self.list_events(start,end) if e['id']!=exclude]
    def get(self,i):
        return self.db.execute('SELECT * FROM calendar_events WHERE id=?',(i,)).fetchone()
    def create_event(self,title,start,end,category,priority,request_id=None):
        return self.db.execute('INSERT INTO calendar_events(title,start,end,category,priority,request_id) VALUES (?,?,?,?,?,?)',(title,start,end,category,priority,request_id)).lastrowid
    def update_event(self,i,start,end):
        self.db.execute('UPDATE calendar_events SET start=?,end=?,revision=revision+1 WHERE id=?',(start,end,i))
    def cancel_event(self,i):
        self.db.execute("UPDATE calendar_events SET status='cancelado' WHERE id=?",(i,))
    def mark_notification(self,key):
        return bool(self.db.execute('INSERT OR IGNORE INTO calendar_notifications VALUES (?)',(key,)).rowcount)
