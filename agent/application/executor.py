import logging
from time import monotonic

from agent.diagnostics import safe_traceback

logger = logging.getLogger(__name__)


class Executor:
    def __init__(self, registry, factory):
        self.registry = registry
        self.factory = factory

    def execute(self, sender, tool, args, *, request_id='-'):
        agent = self.factory.select(sender)
        name = '<desconhecida>'
        started = monotonic()
        try:
            if not isinstance(tool, str):
                raise ValueError('Ferramenta inválida')
            command = self.registry.get(tool)
            name = command.name
            if not agent.permits(command.private):
                raise ValueError('Ferramenta não autorizada')
            if not isinstance(args, dict):
                raise ValueError('Parâmetros inválidos')
            logger.info('execucao_inicio req=%s perfil=%s ferramenta=%s', request_id, agent.role, name)
            result = command.execute(sender, args)
        except Exception as error:
            logger.error('execucao_falhou req=%s perfil=%s ferramenta=%s\n%s',
                         request_id, agent.role, name, safe_traceback(error))
            raise
        logger.info('execucao_concluida req=%s ferramenta=%s duracao_ms=%d',
                    request_id, name, (monotonic() - started) * 1000)
        return result
