import logging

from agent.diagnostics import configure_terminal, safe_traceback
from agent.infrastructure.rag import index

if __name__=='__main__':
    configure_terminal()
    try:
        from dotenv import load_dotenv
        load_dotenv(encoding='utf-8-sig')
        index('public')
        index('private')
    except Exception as error:
        logging.getLogger('agent.infrastructure.rag').error(
            'indexacao_falhou\n%s', safe_traceback(error))
        raise SystemExit(1)
