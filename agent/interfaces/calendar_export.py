"""Explicit local export; no automatic transfer of private data."""
from datetime import datetime,timezone
from pathlib import Path
from agent.domain.calendar import parse
from agent.infrastructure.sqlite import SQLiteUnitOfWork
from agent.infrastructure.calendar_repository import LocalCalendarProvider

def escape(s): return s.replace('\\','\\\\').replace('\r\n','\\n').replace('\n','\\n').replace('\r','\\n').replace(';','\\;').replace(',','\\,')
def fold(line):
    parts=[]; part=''; size=0
    for ch in line:
        n=len(ch.encode('utf8'))
        if size+n>75: parts.append(part); part=' '; size=1
        part+=ch; size+=n
    return '\r\n'.join(parts+[part])
def export(db,path):
    def utc(value): return parse(value).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    with SQLiteUnitOfWork(db).connection() as conn:
        events=LocalCalendarProvider(conn).list_events('1900-01-01 00:00','9999-01-01 00:00')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Personal AI Agent//Calendar V5//PT','CALSCALE:GREGORIAN']
    for e in events:
        lines+=['BEGIN:VEVENT',f"UID:personal-ai-{e['id']}@local",'DTSTAMP:'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'DTSTART:'+utc(e['start']),'DTEND:'+utc(e['end']),'SUMMARY:'+escape(e['title']),'END:VEVENT']
    lines+=['END:VCALENDAR']; Path(path).write_bytes(('\r\n'.join(map(fold,lines))+'\r\n').encode('utf8')); return len(events)
