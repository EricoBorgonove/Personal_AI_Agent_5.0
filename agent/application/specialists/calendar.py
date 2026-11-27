from datetime import timedelta
from agent.domain.calendar import parse,interval,future_interval,FMT
from agent.application.ports import CalendarProvider

class CalendarService:
    def __init__(self,provider:CalendarProvider): self.provider=provider
    def create(self,title,start,end,category='pessoal',priority='normal',request_id=None):
        start,end=future_interval(start,end)
        if not isinstance(title,str) or not title.strip() or len(title)>300: raise ValueError('Título inválido.')
        if not isinstance(category,str) or not category.strip() or len(category)>80: raise ValueError('Categoria inválida.')
        if priority not in ('baixa','normal','alta'): raise ValueError('Prioridade inválida.')
        if self.provider.conflicts(start,end): raise ValueError('Horário indisponível: existe conflito na agenda.')
        return self.provider.create_event(title.strip(),start,end,category,priority,request_id)
    def list(self,start,end): return self.provider.list_events(*interval(start,end))
    def free(self,start,end,minutes):
        start,end=interval(start,end); a,b=parse(start),parse(end)
        if type(minutes) is not int or not 1<=minutes<=1440 or b-a>timedelta(days=31): raise ValueError('Intervalo de até 31 dias e duração de 1 a 1440 minutos.')
        result=[]; cursor=a; delta=timedelta(minutes=minutes)
        for e in self.list(start,end):
            x,y=parse(e['start']),parse(e['end'])
            if min(x,b)-cursor>=delta: result.append({'inicio':cursor.strftime(FMT),'fim':min(x,b).strftime(FMT)})
            cursor=max(cursor,y)
        if b-cursor>=delta: result.append({'inicio':cursor.strftime(FMT),'fim':b.strftime(FMT)})
        return result
    def recurring(self,title,start,end,category,priority,frequency,count):
        if frequency not in ('diaria','semanal') or type(count) is not int or not 1<=count<=52: raise ValueError('Recorrência diária/semanal, 1 a 52 ocorrências.')
        a,b=parse(start),parse(end); step=timedelta(days=1 if frequency=='diaria' else 7)
        slots=[((a+i*step).strftime(FMT),(b+i*step).strftime(FMT)) for i in range(count)]
        if b-a>step or any(self.provider.conflicts(*s) for s in slots): raise ValueError('Conflito na série; nenhuma ocorrência criada.')
        return [self.create(title,*s,category,priority) for s in slots]
    def change(self,i,start,end):
        event=self.provider.get(i)
        if not event or event['status']!='ativo': raise ValueError('Compromisso ativo não encontrado.')
        if event['request_id'] is not None: raise ValueError('Reuniões externas não podem ser alteradas por esta ferramenta.')
        start,end=future_interval(start,end)
        if self.provider.conflicts(start,end,i): raise ValueError('Conflito de horário.')
        self.provider.update_event(i,start,end)
    def cancel(self,i):
        event=self.provider.get(i)
        if not event or event['status']!='ativo': raise ValueError('Compromisso ativo não encontrado.')
        if event['request_id'] is not None: raise ValueError('Reuniões externas não podem ser canceladas por esta ferramenta.')
        self.provider.cancel_event(i)

def register_calendar(add,provider):
    s=CalendarService(provider)
    add('agenda_listar','{"inicio":"AAAA-MM-DD HH:MM","fim":"AAAA-MM-DD HH:MM"}',True,lambda u,a:s.list(a['inicio'],a['fim']))
    add('agenda_criar','{"titulo":"...","inicio":"AAAA-MM-DD HH:MM","fim":"AAAA-MM-DD HH:MM","categoria":"pessoal","prioridade":"normal"}',True,lambda u,a:{'id':s.create(a['titulo'],a['inicio'],a['fim'],a.get('categoria','pessoal'),a.get('prioridade','normal'))})
    add('agenda_disponibilidade','{"inicio":"AAAA-MM-DD HH:MM","fim":"AAAA-MM-DD HH:MM","minutos":60}',True,lambda u,a:s.free(a['inicio'],a['fim'],a['minutos']))
    add('agenda_recorrencia','{"titulo":"...","inicio":"AAAA-MM-DD HH:MM","fim":"AAAA-MM-DD HH:MM","categoria":"pessoal","prioridade":"normal","frequencia":"semanal","quantidade":4}',True,lambda u,a:{'ids':s.recurring(a['titulo'],a['inicio'],a['fim'],a.get('categoria','pessoal'),a.get('prioridade','normal'),a['frequencia'],a['quantidade'])})
