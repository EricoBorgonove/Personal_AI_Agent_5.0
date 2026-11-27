"""Deterministic slot filling based on the current turn and its persisted draft."""
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from agent.domain.working_memory import Draft, DraftRepository

from .dialogue import TIME, explicit_date, explicit_time
from .working_memory_slots import FLOWS, normalize as norm, start_flow


START = re.compile(r'^(?:por favor[, ]+)?(?:agende|marque|cadastre|adicione|coloque|guarde|registre|quero agendar|quero marcar)\s+(?:(?:na|minha|a|o|um|uma|meu|minhas?)\s+|agenda\s+)*(palestra|compromisso|evento|aula|reuniao|consulta)\b', re.I)
OTHER = re.compile(r'^(?:quanto|quais|qual|como|mostre|liste|consulte|lembre|gastei|recebi|paguei|registre|cadastre|agende|marque|adicione|guarde|coloque|quero|tenho|ola|oi|obrigad[oa])\b')
NEG = re.compile(r'\b(?:nao|talvez|se|ou|cancele|cancelar|desistir)\b')
DURATION = re.compile(r'^(?:(?:duracao|durara|dura)(?:\s+de)?\s*:?\s*)?(\d+|uma|um|duas|dois|tres|quatro|cinco|seis)\s*(minutos?|min|horas?|h)[.! ]*$')
WORDS = {'uma':1,'um':1,'duas':2,'dois':2,'tres':3,'quatro':4,'cinco':5,'seis':6}
CALENDAR_CONFIRMATIONS = {'confirmo o compromisso', 'confirmo o rascunho'}
CONFIRMATIONS = CALENDAR_CONFIRMATIONS | {norm(flow.command) for flow in FLOWS.values()}
COMMANDS = {'/contexto', '/cancelar', '/novaconversa'}


def command_text(text):
    return norm(text).rstrip('.! ')

@dataclass
class MemoryDecision:
    reply: str | None = None
    tool: str | None = None
    args: dict | None = None


def extract_times(text):
    times = [explicit_time(match[0]) for match in TIME.finditer(text)]
    return times if all(times) else []


class WorkingMemoryManager:
    def __init__(self, repository: DraftRepository):
        self.repository = repository

    def complete(self, sender, role):
        self.repository.clear(sender, role)

    def route(self, sender, role, authorized, text, today):
        # Caller supplies the authorization from the existing authenticated factory.
        # Text or model output never sets this flag.
        if not authorized:
            return None
        msg = norm(text)
        command = command_text(text)
        draft = self.repository.load(sender, role)
        if command == '/contexto':
            return MemoryDecision(reply=self.describe(draft) if draft else 'Não há compromisso em preparação.')
        if command in ('/cancelar','/novaconversa'):
            if not draft:
                return None
            self.complete(sender, role)
            return MemoryDecision(reply='Rascunho encerrado.')
        start = START.match(msg)
        generic_start = start_flow(command, today)
        if draft and command in ('cancelar','esquece','deixa pra la'):
            self.complete(sender, role)
            return MemoryDecision(reply='Rascunho cancelado.')
        if draft and command in CONFIRMATIONS:
            return self._confirm(draft, command)
        if draft and (generic_start or start and draft.tool != 'agenda_criar'):
            return MemoryDecision(reply='Já existe um rascunho. Use /contexto para retomar ou /cancelar para iniciar outro.')
        if draft and draft.tool in FLOWS:
            return self._fill_generic(sender, role, draft, text, msg, today)
        if generic_start and not draft:
            tool, fields = generic_start
            draft = Draft(tool, fields, {key: value for key, value in fields.items() if key == 'tipo'})
            self.repository.save(sender, role, draft)
            return MemoryDecision(reply=self.describe(draft))
        if start and not draft and (len(extract_times(msg)) >= 2 or re.search(r'\b(?:categoria|prioridade|semanal|recorrente|recorrencia|mensal|todo dia|toda sexta|todas as)\b', msg)):
            # Preserve existing complete/advanced calendar requests.
            return None
        if start and NEG.search(msg):
            return MemoryDecision(reply='Para evitar um agendamento incorreto, informe o compromisso e um único horário desejado.')
        if draft and start:
            return MemoryDecision(reply='Já existe um compromisso em preparação. Use /contexto para consultar ou /cancelar antes de iniciar outro.')
        if not draft and not start:
            return None
        if not draft:
            # Preserve original title spelling; normalized match indices may differ for decomposed Unicode.
            original = unicodedata.normalize('NFC', text).strip()
            tail = original[start.start(1):]
            tail = re.split(
                r'\s+(?:na (?:minha )?agenda|(?:para\s+)?(?:depois de amanh[ãa]|amanh[ãa]|hoje)|'
                r'(?:para|[àa]s|das|em)\s+\d+|com duraç[ãa]o)\b|[,;]',
                tail, maxsplit=1, flags=re.I,
            )[0].strip(' .!?')
            title = tail or start.group(1)
            if len(title) > 300:
                return MemoryDecision(reply='Informe um título de até 300 caracteres.')
            draft = Draft('agenda_criar', {'titulo':title}, {'titulo':title})
        elif OTHER.match(msg):
            # Unrelated requests stay with the normal orchestrator; draft remains intact.
            return None
        slots = draft.slots
        if NEG.search(msg):
            return MemoryDecision(reply='Não alterei o rascunho. Informe uma única data ou horário, ou use /cancelar.')
        if re.search(r'\b(?:semanal|recorrente|recorrencia|mensal|todo dia|toda sexta|todas as)\b',msg):
            if start:
                return None  # Existing recurrence path must remain responsible.
            return MemoryDecision(reply='Este rascunho é de um compromisso único. Use /cancelar e solicite a série recorrente separadamente.')
        day = explicit_date(msg, today)
        if day:
            slots['data'] = day
            draft.evidence['data'] = day
        duration = DURATION.fullmatch(msg)
        if (duration and len(duration[1]) <= 4
                and (duration[2] != 'h' or msg.startswith(('duracao', 'dura')))):
            value = WORDS.get(duration[1], int(duration[1]) if duration[1].isdigit() else 0)
            minutes = value * (60 if duration[2] in ('h','hora','horas') else 1)
            if 1 <= minutes <= 1440:
                slots['minutos'] = minutes
                slots.pop('fim',None)
                draft.evidence['minutos'] = minutes
                draft.evidence.pop('fim',None)
        else:
            times = extract_times(msg)
            if len(times) == 1:
                slots['hora'] = times[0]
                draft.evidence['hora'] = times[0]
            elif len(times) == 2 and re.search(r'\b(?:das|ate|as)\b', msg):
                slots['hora'],slots['fim'] = times
                slots.pop('minutos',None)
                draft.evidence.pop('minutos',None)
                draft.evidence['hora'] = times[0]
                draft.evidence['fim'] = times[1]
        self.repository.save(sender, role, draft)
        return MemoryDecision(reply=self.describe(draft))

    def _confirm(self, draft, command):
        if draft.tool == 'agenda_criar':
            if command in CALENDAR_CONFIRMATIONS and self.ready(draft.slots):
                return MemoryDecision(tool=draft.tool, args=self.args(draft.slots))
        elif draft.tool in FLOWS:
            flow = FLOWS[draft.tool]
            if command == norm(flow.command) and flow.next_slot(draft.slots) is None:
                return MemoryDecision(tool=draft.tool, args=dict(draft.slots))
        return MemoryDecision(reply=self.describe(draft))

    def _fill_generic(self, sender, role, draft, text, msg, today):
        if OTHER.match(msg) or msg.startswith('/') or msg.endswith('?'):
            return None
        if msg in ('sim', 'ok', 'certo', 'entendi') or msg.startswith(('confirmo ', 'nao ', 'talvez ')):
            return MemoryDecision(reply=self.describe(draft))
        flow = FLOWS[draft.tool]
        missing = flow.next_slot(draft.slots)
        if ':' in msg:
            label = msg.split(':', 1)[0]
            missing = next((slot for slot in flow.slots if label in (slot.name, norm(slot.label))), missing)
        if missing:
            value = missing.parse(text, today)
            if value is not None:
                draft.slots[missing.name] = value
                draft.evidence[missing.name] = value
                self.repository.save(sender, role, draft)
        return MemoryDecision(reply=self.describe(draft))

    @staticmethod
    def ready(slots):
        if not all(slots.get(k) for k in ('titulo','data','hora')):
            return False
        if slots.get('minutos'):
            return True
        return bool(slots.get('fim') and slots['fim'] > slots['hora'])

    @staticmethod
    def args(slots):
        a = datetime.fromisoformat(slots['data']+' '+slots['hora'])
        b = a + timedelta(minutes=slots['minutos']) if slots.get('minutos') else datetime.fromisoformat(slots['data']+' '+slots['fim'])
        return {'titulo':slots['titulo'],'inicio':a.strftime('%Y-%m-%d %H:%M'),'fim':b.strftime('%Y-%m-%d %H:%M')}

    def describe(self, draft):
        if draft.tool in FLOWS:
            return FLOWS[draft.tool].summary(draft.slots)
        s = draft.slots
        prefix = f"Compromisso em preparação: {s['titulo']}. "
        if not s.get('data'):
            return prefix+'Qual é a data?'
        if not s.get('hora'):
            return prefix+f"Data: {s['data']}. Qual é o horário de início?"
        if not self.ready(s):
            return prefix+f"Início: {s['data']} às {s['hora']}. Qual será a duração? Ex.: 50 minutos ou duas horas."
        a = self.args(s)
        return prefix+f"De {a['inicio']} até {a['fim']}. Para registrar, responda: Confirmo o compromisso."
