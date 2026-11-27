import re
import unicodedata
from datetime import timedelta

from .planning import PlanError

INTERNAL = re.compile(
    r'\b(?:plano (?:anterior|foi solicitado|foi rejeitado|interno|de marcar)|replanejamento|executando ferramenta|ferramenta rejeitada|'
    r'json|parsing|schema|resultado da ferramenta|erro interno)\b', re.I
)
LABELS = {
    'agenda_reagendar': 'Compromisso reagendado.', 'criar_tarefa': 'Tarefa registrada.', 'concluir_tarefa': 'Atualização de tarefa.',
    'agenda_criar': 'Compromisso registrado.', 'agenda_recorrencia': 'Compromissos registrados.',
    'financeiro_registrar': 'Lançamento registrado.', 'solicitacoes': 'Solicitações encontradas.',
    'tarefas': 'Tarefas encontradas.', 'memorias': 'Memórias encontradas.',
}
HIDDEN_KEYS = {'sender', 'owner', 'recipient', 'actor', 'vector'}


class ResponseBuilder:
    @staticmethod
    def failure():
        return 'Não consegui concluir o pedido. Pode reformular a mensagem?'

    @staticmethod
    def results(results, incomplete=False):
        parts = []
        for tool, result, args in results:
            if tool == 'solicitar_reuniao':
                if result.get('status') == 'PENDENTE':
                    parts.append(f"Registrei a solicitação #{result['id']} com duração de "
                                 f"{args['duracao']} minutos. Ela aguarda aprovação do professor.")
                else:
                    parts.append(result['mensagem'])
            elif isinstance(result, str):
                parts.append(result)
            elif not result:
                parts.append('Não encontrei registros para essa consulta.')
            else:
                label = LABELS.get(tool)
                rows = result if isinstance(result, list) else [result]
                details = '\n'.join(ResponseBuilder._row(row) for row in rows)
                parts.append(f'{label}\n{details}' if label else details)
        if incomplete:
            parts.append('As demais etapas ficaram pendentes. Confira os resultados antes de tentar novamente.')
        return '\n\n'.join(parts)

    @staticmethod
    def _row(value):
        if isinstance(value, dict):
            return ' · '.join(f"{key.replace('_', ' ')}: {ResponseBuilder._row(item)}"
                              for key, item in value.items() if key not in HIDDEN_KEYS)
        if isinstance(value, list):
            return ', '.join(ResponseBuilder._row(item) for item in value)
        return str(value) if value is not None else '—'

    @staticmethod
    def missing_details(fields):
        names = {'titulo': 'título', 'hora': 'horário', 'minutos': 'duração em minutos',
                 'descricao': 'descrição', 'cartao_id': 'cartão', 'revisao': 'compromisso escolhido',
                 'id': 'identificador'}
        labels = ', '.join(names.get(field, field.replace('_', ' ')) for field in fields)
        return f'Não consegui completar os dados do pedido. Pode informar {labels}?'

    @staticmethod
    def model_message(plan, evidence=None, today=None):
        text = plan['message'].strip()
        if INTERNAL.search(text) or COMPLETION_CLAIM.search(text):
            raise PlanError('mensagem_sem_evidencia')
        if evidence is not None and ungrounded_moments(text, evidence, today):
            raise PlanError('data_ou_horario_sem_origem_na_conversa')
        return text

    @staticmethod
    def preview(tool, args, details=None):
        label = PREVIEW_LABELS.get(tool, 'Operação solicitada')
        return f'{label} em preparação.\n{ResponseBuilder._row(details or args)}\nVocê confirma?'

    @staticmethod
    def task_context(active, suspended):
        parts = []
        if active:
            if preview := active.get('preview'):
                parts.append(ResponseBuilder.preview(preview['tool'], preview['args'], preview.get('details')))
            else:
                parts.append(f"Em preparação · {active['tool']}\n{ResponseBuilder._row(active['fields'])}")
        for task in suspended:
            parts.append(f"Rascunho suspenso #{task['id']} · {task['tool']}\n{ResponseBuilder._row(task['fields'])}")
        return '\n\n'.join(parts) or 'Nenhum rascunho em andamento.'


COMPLETION_CLAIM = re.compile(
    r'\b(?:agendei|reagendei|confirmei|registrei|lancei|estornei|liquidei|salvei|enviei|'
    r'(?:foi|está|foram|estão) (?:agendad|reagendad|confirmad|registrad|enviad)[oa]s?)\b', re.I
)

MONTHS = ('janeiro', 'fevereiro', 'marco', 'abril', 'maio', 'junho', 'julho', 'agosto',
          'setembro', 'outubro', 'novembro', 'dezembro')
CLOCK = re.compile(r'(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d])')
HOUR = re.compile(r'\b(?:as|das|ate|para)\s+([01]?\d|2[0-3])(?:h([0-5]\d)?|\s*horas?)?(?![\d:])')
ISO_DATE = re.compile(r'(?<!\d)\d{4}-(\d{2})-(\d{2})(?!\d)')
BR_DATE = re.compile(r'(?<![\d/])(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])')
NAMED_DATE = re.compile(r'\b(\d{1,2})\s+de\s+(' + '|'.join(MONTHS) + r')\b')
RELATIVE_DAYS = (('depois de amanha', 2), ('amanha', 1), ('hoje', 0))


def _plain(text):
    decomposed = unicodedata.normalize('NFKD', text.casefold())
    return ''.join(char for char in decomposed if not unicodedata.combining(char))


def _moments(text, *, loose_hours):
    """Times as (hour, minute) and dates as (month, day) mentioned in a text."""
    times = {(int(h), int(m)) for h, m in CLOCK.findall(text)}
    if loose_hours:
        times |= {(int(h), int(m or 0)) for h, m in HOUR.findall(text)}
        times |= {(int(h), int(m or 0)) for h, m in re.findall(r'(?<![\d:])([01]?\d|2[0-3])h([0-5]\d)?\b', text)}
    dates = {(int(m), int(d)) for m, d in ISO_DATE.findall(text)}
    dates |= {(int(m), int(d)) for d, m in BR_DATE.findall(text)}
    dates |= {(MONTHS.index(m) + 1, int(d)) for d, m in NAMED_DATE.findall(text)}
    return times, dates


def ungrounded_moments(message, evidence, today=None):
    """True when the model message cites a time or date that nobody in the conversation provided."""
    message, evidence = _plain(message), _plain(evidence)
    # Format hints ("por exemplo, 15h ou 15:30") are not claims about the task.
    message = re.sub(r'\bexemplo\b[^.?!]*', ' ', message)
    times, dates = _moments(message, loose_hours=False)
    times |= {(int(h), int(m or 0)) for h, m in HOUR.findall(message)}
    known_times, known_dates = _moments(evidence, loose_hours=True)
    if today is not None:
        remaining = evidence
        for word, offset in RELATIVE_DAYS:
            if word in remaining:
                remaining = remaining.replace(word, ' ')
                day = today + timedelta(days=offset)
                known_dates.add((day.month, day.day))
    return bool(times - known_times or dates - known_dates)


PREVIEW_LABELS = {
    'agenda_criar': 'Compromisso', 'agenda_reagendar': 'Reagendamento',
    'financeiro_registrar': 'Lançamento', 'criar_tarefa': 'Tarefa',
}
