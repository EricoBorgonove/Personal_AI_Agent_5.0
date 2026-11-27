"""Calendar invariants; local wall-clock times in America/Manaus."""
from datetime import datetime, timedelta
from agent.domain.policies import now, TZ

FMT = '%Y-%m-%d %H:%M'
def parse(value):
    if not isinstance(value,str): raise ValueError('Informe data e hora AAAA-MM-DD HH:MM')
    return datetime.strptime(value,FMT).replace(tzinfo=TZ)
def interval(start,end):
    a,b=parse(start),parse(end)
    if b<=a: raise ValueError('Fim deve ser posterior ao início.')
    return a.strftime(FMT),b.strftime(FMT)
def future_interval(start,end):
    a,b=interval(start,end)
    if parse(a)<=now(): raise ValueError('Compromisso deve estar no futuro.')
    return a,b
def meeting_end(slot): return (parse(slot)+timedelta(hours=1)).strftime(FMT)
