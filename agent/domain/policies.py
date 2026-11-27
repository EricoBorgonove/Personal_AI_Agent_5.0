from datetime import datetime
from zoneinfo import ZoneInfo
TZ = ZoneInfo('America/Manaus')
def now(): return datetime.now(TZ)
def valid_time(s):
    dt=datetime.strptime(s,'%Y-%m-%d %H:%M').replace(tzinfo=TZ)
    if dt<=now(): raise ValueError('O horário deve estar no futuro.')
    return dt.strftime('%Y-%m-%d %H:%M')

