import re
from datetime import timedelta

from agent.domain.calendar import parse
from agent.domain.finance import cents

from .dialogue import DATE, TIME, explicit_date, explicit_time


MONEY_FIELDS = {'valor', 'valor_total', 'limite'}
DATE_FIELDS = {'data', 'vencimento', 'primeiro_vencimento'}
NUMBER_FIELDS = {'id', 'cartao_id', 'meses', 'parcelas', 'fechamento', 'vencimento', 'quantidade'}
WRITE_INTENTS = {
    'criar_tarefa': r'\b(?:tarefa|pend[êe]ncia)\b',
    'concluir_tarefa': r'\b(?:conclu[ai]|finaliz[ae]|marque|terminei|completei)\b',
    'salvar_memoria': r'\b(?:lembre|memorize|salve|mem[óo]ria|guarde)\b',
    'agenda_criar': r'\b(?:agenda|compromisso|evento|agende)\b',
    'agenda_recorrencia': r'\b(?:recorr[êe]ncia|recorrente|semanal|mensal|di[áa]ri[oa])\b',
    'financeiro_registrar': r'\b(?:registre|lance|gastei|paguei|recebi|despesa|receita|lan[çc]amento)\b',
    'financeiro_orcamento': r'\bor[çc]amento\b',
    'financeiro_cartao': r'\bcart[ãa]o\b',
    'financeiro_criar_conta': r'\b(?:conta|vencimento|a pagar|a receber)\b',
    'financeiro_recorrencia': r'\b(?:recorr[êe]ncia|recorrente|mensal|meses)\b',
    'financeiro_compra_parcelada': r'\b(?:parcelas?|parcelad[ao])\b',
}
NUMBER = re.compile(r'(?<!\w)(\d+(?:[,.]\d{1,2})?)(?!\w)')
DURATION = re.compile(r'\b(\d+)\s*min(?:utos?)?\b', re.I)
DECLINED_WRITE = re.compile(r'\bn[ãa]o\s+(?:crie|conclua|registre|agende|salve|cadastre|lance|'
                            r'memorize|adicione|quero|preciso)\b', re.I)


def missing_write_evidence(tool, args, text, today):
    intent = WRITE_INTENTS.get(tool)
    if intent is None:
        return None
    if DECLINED_WRITE.search(text) or not re.search(intent, text, re.I):
        return 'a ação desejada'
    dates = {explicit_date(match[0], today) for match in DATE.finditer(text)}
    hours = {explicit_time(match[0]) for match in TIME.finditer(text)}
    numbers = set(NUMBER.findall(DATE.sub('', TIME.sub('', text))))
    money = set()
    for number in numbers:
        try:
            money.add(cents(number))
        except ValueError:
            continue

    for field, value in args.items():
        if field in MONEY_FIELDS:
            if cents(value) not in money:
                return 'o valor'
        elif field in DATE_FIELDS and isinstance(value, str):
            if value not in dates:
                return 'a data'
        elif field in NUMBER_FIELDS and isinstance(value, int):
            if str(value) not in numbers:
                return field.replace('_', ' ')
        elif field in ('inicio', 'fim'):
            day, _, hour = value.partition(' ')
            if day in dates and hour in hours:
                continue
            duration = DURATION.search(text)
            if field == 'fim' and duration and args.get('inicio'):
                start = parse(args['inicio'])
                if parse(value) == start + timedelta(minutes=int(duration[1])):
                    continue
            return 'o dia e o horário de início e fim ou a duração'
    return None
