import logging
from time import monotonic

from agent.diagnostics import safe_traceback

from .tools import allowed

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
            if not allowed(agent, command):
                raise ValueError('Ferramenta não autorizada')
            if not isinstance(args, dict):
                raise ValueError('Parâmetros inválidos')
            logger.info('[EXECUTOR] inicio req=%s perfil=%s ferramenta=%s', request_id, agent.role, name)
            result = command.execute(sender, args)
        except Exception as error:
            logger.error('[ERROR] execucao_falhou req=%s perfil=%s ferramenta=%s\n%s',
                         request_id, agent.role, name, safe_traceback(error))
            raise
        logger.info('[EXECUTOR] concluida req=%s ferramenta=%s duracao_ms=%d',
                    request_id, name, (monotonic() - started) * 1000)
        return result
