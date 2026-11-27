import re

from .grounding import ungrounded_moments
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
        """``evidence`` is a grounding.Evidence or the plain conversation text."""
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

PREVIEW_LABELS = {
    'agenda_criar': 'Compromisso', 'agenda_reagendar': 'Reagendamento',
    'financeiro_registrar': 'Lançamento', 'criar_tarefa': 'Tarefa',
}
