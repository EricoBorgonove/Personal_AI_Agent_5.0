from datetime import timedelta
from agent.domain.policies import now
from agent.domain.calendar import FMT,parse

class CalendarReminderService:
    def __init__(self,repo,owner): self.repo,self.owner=repo,owner
    def enqueue(self,current=None):
        current=current or now(); p=self.repo.calendar; count=0
        def notify(key,text):
            nonlocal count
            if p.mark_notification(key): self.repo.notify(self.owner,text); count+=1
        for e in p.list_events(current.strftime(FMT),(current+timedelta(minutes=31)).strftime(FMT)):
            if current<=parse(e['start'])<=current+timedelta(minutes=30):
                notify(f"event:{e['id']}:{e['revision']}",f"Lembrete privado: {e['title']} às {e['start']}.")
        if current.hour>=7:
            day=current.replace(hour=0,minute=0,second=0,microsecond=0)
            for name,days in [('diario',1)]+([('semanal',7)] if day.weekday()==0 else []):
                events=p.list_events(day.strftime(FMT),(day+timedelta(days=days)).strftime(FMT))
                lines=[f"{e['start']} — {e['title']}" for e in events]
                notify(f'{name}:{day.date()}',f'Resumo {name} da agenda:\n'+ ('\n'.join(lines) or 'Sem compromissos.'))
        return count
