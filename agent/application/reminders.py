"""Queue private daily reminders transactionally; no external payment actions."""
from datetime import timedelta
from agent.domain.policies import now
from agent.domain.finance import money

class FinanceReminderService:
    def __init__(self,repository,owner): self.repository,self.owner=repository,owner
    def enqueue(self,today=None):
        today=today or now().date(); repo=self.repository
        pending=repo.obligations.list('0001-01-01',(today+timedelta(days=3)).isoformat(),'pendente')
        fresh=[r for r in pending if repo.obligations.mark_reminder(r['id'],today.isoformat())]
        if fresh:
            lines=['Lembrete financeiro privado — contas vencidas ou a vencer em até 3 dias:']
            for r in fresh:
                kind='A pagar' if r['kind']=='despesa' else 'A receber'
                lines.append(f"#{r['id']} | {kind} | {r['description']} | R$ {money(r['amount_cents'])} | {r['due_date']}")
            for i in range(1,len(lines),15): repo.notify(self.owner,'\n'.join([lines[0]]+lines[i:i+15]))
        return len(fresh)
