from .sqlite import rows

class ObligationsRepository:
    def __init__(self,db): self.db=db
    def create_card(self,name,limit,closing,due):
        return self.db.execute('INSERT INTO finance_cards(name,limit_cents,closing_day,due_day) VALUES (?,?,?,?)',(name,limit,closing,due)).lastrowid
    def card(self,i):
        r=self.db.execute('SELECT * FROM finance_cards WHERE id=?',(i,)).fetchone()
        if not r: raise ValueError('Cartão não encontrado')
        return dict(r)
    def cards(self):
        return rows(self.db,"SELECT c.*, COALESCE((SELECT SUM(o.amount_cents) FROM finance_obligations o WHERE o.card_id=c.id AND o.status='pendente'),0) AS committed FROM finance_cards c ORDER BY c.id")
    def create(self,kind,desc,cat,amount,due,card=None,series=None,part=None,total=None):
        return self.db.execute('INSERT INTO finance_obligations(kind,description,category,amount_cents,due_date,card_id,series,installment,total_installments) VALUES (?,?,?,?,?,?,?,?,?)',(kind,desc,cat,amount,due,card,series,part,total)).lastrowid
    def get(self,i):
        r=self.db.execute('SELECT * FROM finance_obligations WHERE id=?',(i,)).fetchone()
        if not r: raise ValueError('Conta não encontrada')
        return dict(r)
    def list(self,start,end,status=None,card=None):
        return rows(self.db,'SELECT * FROM finance_obligations WHERE due_date BETWEEN ? AND ? AND (? IS NULL OR status=?) AND (? IS NULL OR card_id=?) ORDER BY due_date,id',(start,end,status,status,card,card))
    def settle(self,i,entry):
        if not self.db.execute("UPDATE finance_obligations SET status='liquidado',entry_id=? WHERE id=? AND status='pendente'",(entry,i)).rowcount: raise ValueError('Conta não está pendente')
    def cancel(self,i):
        if not self.db.execute("UPDATE finance_obligations SET status='cancelado' WHERE id=? AND status='pendente'",(i,)).rowcount: raise ValueError('Conta não está pendente')
    def mark_reminder(self,i,day):
        return self.db.execute('INSERT OR IGNORE INTO finance_reminder_log VALUES (?,?)',(i,day)).rowcount
