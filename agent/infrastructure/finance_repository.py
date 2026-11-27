from .sqlite import rows

class FinanceRepository:
    def __init__(self, db): self.db=db
    def add(self,kind,amount,category,description,day):
        return self.db.execute('INSERT INTO finance_entries(kind,amount_cents,category,description,day) VALUES (?,?,?,?,?)',(kind,amount,category,description,day)).lastrowid
    def entries(self,month):
        return rows(self.db,'SELECT * FROM finance_entries WHERE substr(day,1,7)=? ORDER BY day,id',(month,))
    def totals(self,month):
        return rows(self.db,'SELECT kind,category,SUM(amount_cents) AS total FROM finance_entries WHERE substr(day,1,7)=? AND voided=0 GROUP BY kind,category',(month,))
    def budget(self,month,category,amount):
        self.db.execute('INSERT INTO finance_budgets VALUES (?,?,?) ON CONFLICT(month,category) DO UPDATE SET amount_cents=excluded.amount_cents',(month,category,amount))
    def budgets(self,month):
        return rows(self.db,'SELECT category,amount_cents FROM finance_budgets WHERE month=? ORDER BY category',(month,))
    def void(self,entry):
        return self.db.execute('UPDATE finance_entries SET voided=1 WHERE id=? AND voided=0 AND NOT EXISTS (SELECT 1 FROM finance_obligations WHERE entry_id=finance_entries.id)',(entry,)).rowcount
