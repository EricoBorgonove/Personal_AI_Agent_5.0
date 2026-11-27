import re

from .dialogue import Intent

INTERNAL = re.compile(
    r'\b(?:plano (?:anterior|foi solicitado|foi rejeitado|interno|de marcar)|replanejamento|executando ferramenta|ferramenta rejeitada|'
    r'json|parsing|schema|resultado da ferramenta|erro interno)\b', re.I
)
UNVERIFIED = re.compile(
    r'\d|\b(?:agendad[ao]|confirmad[ao]|marcad[ao]|registrad[ao]|aprovad[ao]|'
    r'protocolo|amanhã|ontem|agendei|marquei|registrei|confirmei|salvei|criei|'
    r'será (?:marcad[ao]|realizad[ao]|confirmad[ao])|sem compromissos|seu saldo|não encontrei|'
    r'reais|segunda-feira|terça-feira|quarta-feira|quinta-feira|sexta-feira|sábado|domingo)\b',
    re.I
)
LABELS = {
    'criar_tarefa': 'Tarefa registrada.', 'concluir_tarefa': 'Atualização de tarefa.',
    'agenda_criar': 'Compromisso registrado.', 'agenda_recorrencia': 'Compromissos registrados.',
    'financeiro_registrar': 'Lançamento registrado.', 'solicitacoes': 'Solicitações encontradas.',
    'tarefas': 'Tarefas encontradas.', 'memorias': 'Memórias encontradas.',
}
HIDDEN_KEYS = {'sender', 'owner', 'recipient', 'actor', 'vector'}
OPERATIONAL = re.compile(r'\b(?:reuni[aã]o|reuniões|solicitaç[ãa]o|agenda|compromissos?|saldo|'
                         r'extrato|finan[çc]as|financeir[oa]|despesa|tarefa|recado|documentos?)\b', re.I)


class ResponseBuilder:
    @staticmethod
    def conversation(plan, intent, user_text):
        text = plan['message'].strip()
        if INTERNAL.search(text) or UNVERIFIED.search(text):
            return ResponseBuilder.clarify(intent)
        if plan['action'] == 'RESPONDER' and (intent == Intent.TOOL or OPERATIONAL.search(user_text)):
            return ResponseBuilder.clarify(intent)
        if plan['action'] == 'PERGUNTAR' and '?' not in text:
            return ResponseBuilder.clarify(intent)
        return text

    @staticmethod
    def clarify(intent):
        if intent == Intent.CONVERSATION:
            return 'Posso ajudar. Sobre o que você gostaria de conversar?'
        return 'Pode me dar mais detalhes sobre o que você precisa?'

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
