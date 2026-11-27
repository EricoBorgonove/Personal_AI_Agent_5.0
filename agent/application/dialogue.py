import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from agent.domain.policies import valid_time


class Intent(StrEnum):
    GREETING = 'saudacao'
    CONVERSATION = 'conversa'
    QUESTION = 'pergunta'
    INFORMATION = 'informacao'
    MEETING = 'reuniao'
    NOTE = 'recado'
    CONFIRMATION = 'confirmacao'
    COUNTERPROPOSAL = 'contraproposta'
    INCOMPLETE = 'incompleta'
    TOOL = 'ferramenta'


DATE = re.compile(r'\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|depois de amanh[ãa]|amanh[ãa]|hoje)\b', re.I)
TIME = re.compile(r'\b(\d{1,2})(?:\:(\d{2})|h(\d{2})?)(?!\w)', re.I)
DURATION = re.compile(r'\bdura(?:ção|r)\s*:?\s*(?:de\s+)?(\d+)\s*(min(?:utos?)?|h(?:oras?)?)?\b', re.I)
BARE_DURATION = re.compile(r'\b(\d+)\s*(min(?:utos?)?)\b', re.I)
DURATION_ANSWER = re.compile(r'(\d+)\s*(min(?:utos?)?|h(?:oras?)?)?[.!\s]*', re.I)
SUBJECT = re.compile(
    r'\b(?:assunto\s*:\s*|reuni[aã]o\s+(?:sobre|para)\s+'
    r'(?!hoje\b|amanh[ãa]\b|depois de\b|[àa]s\b|\d|segunda\b|terça\b|quarta\b|quinta\b|sexta\b|sábado\b|domingo\b))'
    r'(.+?)(?=\s*(?:[.;\n]|[, ]+(?:data\b|hor[aá]rio\b|duraç[aã]o\b|às\b|amanh[ãa]\b|hoje\b|\d{4}-\d{2}-\d{2}))|$)',
    re.I,
)
NAME = re.compile(r'\bnome\s*:\s*([^.;\n,]+)', re.I)
MEETING = re.compile(r'(?=.*\breuni[aã]o\b)(?=.*\b(?:marcar|agendar|solicitar|solicito|marque|agende|quero|gostaria|podemos|pedir)\b)', re.I | re.S)
NOTE = re.compile(r'^(?:(?:quero|gostaria de|posso)\s+)?(?:deixar|enviar|registrar|deixe|registre|envie)\s+(?:um\s+)?recado\b(?:\s+(?:para o|pro|ao)\s+professor)?\s*[:–-]?\s*(.*)$', re.I | re.S)
GREETING = re.compile(r'(?:olá|oi|opa|bom dia|boa tarde|boa noite|tudo bem)[.!?\s]*', re.I)
THANKS = re.compile(r'(?:obrigad[ao]|valeu|muito obrigad[ao])[.!\s]*', re.I)
INFORMAL = re.compile(r'(?:precisamos conversar|podemos conversar|quero conversar|gostaria de conversar)[.!?\s]*', re.I)
DOCUMENT_SCOPE = re.compile(r'\b(?:documentos?|materiais?|base de conhecimento)\s+(p[úu]blic[oa]s?|privad[oa]s?)\b', re.I)
DECLINED_DRAFT = {'cancelar', 'cancelar pedido', 'esquece', 'desistir', 'deixa pra lá'}
DECLINED_MEETING = re.compile(r'\bn[ãa]o\s+(?:quero|vamos|marque|agende|solicite|preciso)\b', re.I)
REJECTED_SLOT = re.compile(r'\bn[ãa]o\s+(?:posso|consigo|d[aá]|pode|serve|funciona)\b', re.I)
PROMPTS = {
    'assunto': 'Qual é o assunto da reunião?',
    'data': 'Qual dia seria melhor para a reunião? Pode informar a data ou dizer, por exemplo, “amanhã”.',
    'hora': 'Qual horário seria melhor para a reunião? Pode informar, por exemplo, “15h” ou “15:30”.',
    'duracao': 'Qual é a duração desejada, em minutos?',
}


@dataclass
class DialogueDecision:
    intent: Intent
    reply: str | None = None
    tool: str | None = None
    args: dict = field(default_factory=dict)
    missing: str | None = None


def explicit_date(text, today):
    matches = DATE.findall(text)
    if len(matches) != 1:
        return None
    value = matches[0].casefold().replace('ã', 'a')
    relative = {'hoje': 0, 'amanha': 1, 'depois de amanha': 2}
    try:
        if value in relative:
            return (today + timedelta(days=relative[value])).isoformat()
        if '/' in value:
            day, month, year = map(int, value.split('/'))
            return date(year, month, day).isoformat()
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def explicit_time(text):
    matches = TIME.findall(DURATION.sub('', text))
    if len(matches) != 1:
        return None
    hour, colon_minutes, h_minutes = matches[0]
    h, m = int(hour), int(colon_minutes or h_minutes or 0)
    return f'{h:02d}:{m:02d}' if h < 24 and m < 60 else None


class DialogueManager:
    def __init__(self, default_duration):
        self.default_duration = default_duration

    def route(self, repo, sender, text, today, display_name=None):
        current = repo.dialogue(sender)
        clean = text.strip()
        if current and clean.casefold().rstrip('.!?') in DECLINED_DRAFT:
            repo.clear_dialogue(sender)
            return DialogueDecision(Intent.CONVERSATION, 'Tudo bem, descartei os dados deste pedido.')
        if GREETING.fullmatch(clean):
            return DialogueDecision(Intent.GREETING, 'Olá! Como posso ajudar você hoje?')
        if THANKS.fullmatch(clean):
            return DialogueDecision(Intent.CONVERSATION, 'De nada! Estou à disposição.')
        if INFORMAL.fullmatch(clean):
            return DialogueDecision(Intent.CONVERSATION, 'Claro, podemos conversar. Sobre o que você gostaria de falar?')
        if MEETING.search(clean) and DECLINED_MEETING.search(clean):
            return DialogueDecision(Intent.CONVERSATION, 'Tudo bem.')
        if MEETING.search(clean) or (current and current['kind'] == 'meeting'):
            return self._meeting(repo, sender, clean, today, display_name, current)
        if note := NOTE.fullmatch(clean):
            clean = note[1].strip(' .!?')
            if not clean:
                repo.save_dialogue(sender, {'kind': 'note'})
                return DialogueDecision(Intent.INCOMPLETE, 'Qual recado você gostaria de deixar?', missing='texto')
            return DialogueDecision(Intent.NOTE, tool='registrar_recado', args={'texto': clean})
        if current and current['kind'] == 'note':
            return DialogueDecision(Intent.NOTE, tool='registrar_recado', args={'texto': clean})
        if scope := DOCUMENT_SCOPE.search(clean):
            tool = 'rag_privado' if scope[1].casefold().startswith('privad') else 'rag_publico'
            return DialogueDecision(Intent.INFORMATION, tool=tool, args={'busca': clean})
        if re.search(r'\b(informaç(?:ão|ões)|documentos?|base de conhecimento|consult[ae])\b', clean, re.I):
            return DialogueDecision(Intent.INFORMATION)
        if clean.endswith('?'):
            return DialogueDecision(Intent.QUESTION)
        if re.search(r'^(?:por favor[, ]+)?(?:crie|registre|liste|mostre|salve|consulte|adicione|conclua|quero|preciso|lembre|exiba|gastei|paguei|recebi|agende|memorize|cadastre)\b', clean, re.I):
            return DialogueDecision(Intent.TOOL)
        return DialogueDecision(Intent.CONVERSATION)

    def _meeting(self, repo, sender, text, today, display_name, current):
        slots = dict(current) if current and current['kind'] == 'meeting' else {'kind': 'meeting'}
        scheduling = SUBJECT.sub('', NAME.sub('', DURATION.sub('', text)))
        rejected = REJECTED_SLOT.search(scheduling)
        if DATE.search(scheduling):
            slots['data'] = None if rejected else explicit_date(scheduling, today)
        if TIME.search(scheduling):
            slots['hora'] = None if rejected else explicit_time(scheduling)
        if name := NAME.search(text):
            slots['nome'] = name[1].strip()[:150]
        if subject := SUBJECT.search(text):
            slots['assunto'] = subject[1].strip(' ,:?')[:300]
        elif 'assunto' not in slots and current and current['kind'] == 'meeting' and not (
            MEETING.search(text) or re.search(r'\d', text) or DATE.search(text) or text.endswith('?')
        ):
            slots['assunto'] = text.strip(' .,!?')[:300]
        duration = DURATION.search(text) or BARE_DURATION.search(scheduling)
        if duration is None and 'duracao' in slots and slots['duracao'] is None:
            duration = DURATION_ANSWER.fullmatch(text)
        if duration:
            unit = 60 if (duration[2] or '').lower().startswith('h') else 1
            minutes = int(duration[1]) * unit if len(duration[1]) <= 4 else 0
            slots['duracao'] = minutes if 1 <= minutes <= 1440 else None
        if 'nome' not in slots and display_name:
            slots['nome'] = ' '.join(display_name.split())[:150]
        repo.save_dialogue(sender, slots)
        for field in ('assunto', 'data', 'hora', 'duracao'):
            if not slots.get(field, self.default_duration if field == 'duracao' else None):
                return DialogueDecision(Intent.INCOMPLETE, PROMPTS[field], missing=field)
        try:
            when = valid_time(f"{slots['data']} {slots['hora']}")
        except ValueError:
            slots.pop('data', None)
            slots.pop('hora', None)
            repo.save_dialogue(sender, slots)
            return DialogueDecision(Intent.INCOMPLETE, 'Informe um dia e horário futuros para a reunião.',
                                    missing='data,hora')
        return DialogueDecision(Intent.MEETING, tool='solicitar_reuniao', args={
            'nome': slots.get('nome') or 'Solicitante',
            'assunto': slots['assunto'],
            'horario': when,
            'duracao': slots.get('duracao', self.default_duration),
        })
