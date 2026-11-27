"""Check that times, dates and durations proposed by the model were said in the conversation.

The model interprets the language; these checks only ask whether a concrete value has any
source in what the user, the history, the stored task or a tool result provided.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta

MONTHS = ('janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho', 'julho', 'agosto',
          'setembro', 'outubro', 'novembro', 'dezembro')
WEEKDAYS = (('segunda',), ('terca',), ('quarta',), ('quinta',), ('sexta',), ('sabado',), ('domingo',))
UNITS = {'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6,
         'sete': 7, 'oito': 8, 'nove': 9}
TEENS = {'dez': 10, 'onze': 11, 'doze': 12, 'treze': 13, 'quatorze': 14, 'catorze': 14, 'quinze': 15,
         'dezesseis': 16, 'dezessete': 17, 'dezoito': 18, 'dezenove': 19}
TENS = {'vinte': 20, 'trinta': 30, 'quarenta': 40, 'cinquenta': 50}
# "uma reunião" is an article; "à uma", "das duas" and "uma hora" are quantities.
ARTICLE_SAFE = {'a', 'as', 'da', 'das', 'ate', 'para'}

CLOCK = re.compile(r'(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d])')
HOUR = re.compile(r'\b(?:as|das|ate|para)\s+([01]?\d|2[0-3])(?:h([0-5]\d)?|\s*horas?)?(?![\d:])')
H_FORM = re.compile(r'(?<![\d:])([01]?\d|2[0-3])h([0-5]\d)?\b')
ISO_DATE = re.compile(r'(?<!\d)\d{4}-(\d{2})-(\d{2})(?!\d)')
BR_DATE = re.compile(r'(?<![\d/])(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])')
NAMED_DATE = re.compile(r'\b(\d{1,2})\s+de\s+(' + '|'.join(MONTHS) + r')\b')
DAY_OF_MONTH = re.compile(r'\bdia\s+(\d{1,2})\b')
RELATIVE_DAYS = (('depois de amanha', 2), ('amanha', 1), ('hoje', 0))
EXAMPLE = re.compile(r'\bexemplo\b[^.?!]*')
CHECKED_TOOLS = {'agenda_criar', 'agenda_recorrencia', 'agenda_reagendar', 'solicitar_reuniao'}


def plain(text):
    decomposed = unicodedata.normalize('NFKD', text.casefold())
    return EXAMPLE.sub(' ', ''.join(char for char in decomposed if not unicodedata.combining(char)))


def spoken_numbers(text):
    """Numbers written in words or standalone digits: "vinte e uma" -> 21, "nove" -> 9, "50" -> 50.

    Digits inside dates, times or amounts ("2026-12-10", "35,90") are not standalone numbers.
    """
    numbers = {int(value) for value in re.findall(r'(?<![\d\-/:.,])\d{1,4}(?![\d\-/:.,]|h\d)', text)}
    words = re.findall(r'[a-z]+', text)
    for index, word in enumerate(words):
        if word in UNITS and word in ('um', 'uma'):
            before = words[index - 1] if index else ''
            after = words[index + 1] if index + 1 < len(words) else ''
            if before not in ARTICLE_SAFE and before != 'e' and not after.startswith('hora'):
                continue
        value = UNITS.get(word) or TEENS.get(word) or TENS.get(word)
        if value is None:
            continue
        numbers.add(value)
        if word in TENS and index + 2 < len(words) and words[index + 1] == 'e' and words[index + 2] in UNITS:
            numbers.add(value + UNITS[words[index + 2]])
    if 'meio dia' in text or 'meio-dia' in text:
        numbers.add(12)
    return numbers


def _times(text, *, loose):
    times = {(int(h), int(m)) for h, m in CLOCK.findall(text)}
    times |= {(int(h), int(m or 0)) for h, m in HOUR.findall(text)}
    if loose:
        times |= {(int(h), int(m or 0)) for h, m in H_FORM.findall(text)}
    return times


def _dates(text):
    dates = {(int(m), int(d)) for m, d in ISO_DATE.findall(text)}
    dates |= {(int(m), int(d)) for d, m in BR_DATE.findall(text)}
    dates |= {(MONTHS.index(m) + 1, int(d)) for d, m in NAMED_DATE.findall(text)}
    return dates


def _relative_dates(text, today):
    found, remaining = set(), text
    for word, offset in RELATIVE_DAYS:
        if word in remaining:
            remaining = remaining.replace(word, ' ')
            found.add(today + timedelta(days=offset))
    return found


class Evidence:
    """What the user said (``speech``) and exact values from stored data (``records``).

    Spoken numbers, relative days and weekdays only count when the user said them; state,
    tool results and earlier replies only ground exact times and dates.
    """

    def __init__(self, speech, records='', today=None):
        self.text = plain(speech)
        records = plain(records)
        self.today = today
        self.times = _times(self.text, loose=True) | _times(records, loose=True)
        self.dates = _dates(self.text) | _dates(records)
        self.numbers = spoken_numbers(self.text)
        self.relative = _relative_dates(self.text, today) if today else set()

    def has_time(self, hour, minute):
        if (hour, minute) in self.times:
            return True
        hour_said = hour in self.numbers or (hour > 12 and hour - 12 in self.numbers) or (hour == 0 and 'meia noite' in self.text)
        if minute == 0:
            return hour_said
        minute_said = minute in self.numbers or (minute == 30 and 'meia' in self.text)
        return hour_said and minute_said

    def has_date(self, value):
        if (value.month, value.day) in self.dates or value in self.relative:
            return True
        if any(int(day) == value.day for day in DAY_OF_MONTH.findall(self.text)):
            return True
        if self.today and 0 <= (value - self.today).days <= 13:
            return any(name in self.text for name in WEEKDAYS[value.weekday()])
        return False

    def has_minutes(self, minutes):
        if minutes in self.numbers:
            return True
        hours, rest = divmod(minutes, 60)
        if 'hora' not in self.text:
            return False
        if rest == 0:
            return hours in self.numbers
        if rest == 30:
            return 'meia' in self.text and (hours == 0 or hours in self.numbers)
        return False


def _start(fields):
    if 'inicio' in fields or 'horario' in fields:
        return datetime.strptime(fields.get('inicio') or fields['horario'], '%Y-%m-%d %H:%M')
    if 'data' in fields and 'hora' in fields:
        return datetime.strptime(fields['data'] + ' ' + fields['hora'], '%Y-%m-%d %H:%M')
    return None


def ungrounded_fields(tool, fields, evidence, context=None):
    """Names of temporal fields whose values have no source in the evidence.

    ``context`` holds every field of the task (stored and proposed); an end that is the
    start plus a duration the user said counts as grounded.
    """
    if tool not in CHECKED_TOOLS:
        return []
    start = _start({**(context or {}), **fields})

    def spoken_duration(end):
        return start is not None and end > start and evidence.has_minutes(int((end - start).total_seconds() // 60))

    missing = []
    if 'data' in fields and not evidence.has_date(date.fromisoformat(fields['data'])):
        missing.append('data')
    if 'hora' in fields and not evidence.has_time(*map(int, fields['hora'].split(':'))):
        missing.append('hora')
    if 'fim_hora' in fields:
        hour, minute = map(int, fields['fim_hora'].split(':'))
        end = start.replace(hour=hour, minute=minute) if start else None
        if not evidence.has_time(hour, minute) and not (end and spoken_duration(end)):
            missing.append('fim_hora')
    for key in ('inicio', 'horario', 'fim'):
        if key in fields:
            stamp = datetime.strptime(fields[key], '%Y-%m-%d %H:%M')
            said = evidence.has_date(stamp.date()) and evidence.has_time(stamp.hour, stamp.minute)
            if not said and not (key == 'fim' and spoken_duration(stamp)):
                missing.append(key)
    if 'minutos' in fields and not evidence.has_minutes(fields['minutos']):
        missing.append('minutos')
    return missing


def ungrounded_moments(message, evidence, today=None):
    """True when a model message cites a time or date that nobody in the conversation provided."""
    known = evidence if isinstance(evidence, Evidence) else Evidence(evidence, today=today)
    text = plain(message)
    if any(not known.has_time(h, m) for h, m in _times(text, loose=False)):
        return True
    year = (known.today or date.today()).year
    for month, day in _dates(text):
        try:
            value = date(year, month, day)
        except ValueError:
            return True
        if known.today and value < known.today:
            value = value.replace(year=year + 1)
        if not known.has_date(value):
            return True
    return False
