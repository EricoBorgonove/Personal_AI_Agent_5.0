import argparse
import logging
from pathlib import Path

from agent.diagnostics import configure_terminal, safe_traceback


def main():
    configure_terminal()
    from dotenv import load_dotenv
    load_dotenv(encoding='utf-8-sig')
    parser=argparse.ArgumentParser(); parser.add_argument('--terminal',action='store_true'); parser.add_argument('--export-calendar'); parser.add_argument('--db'); args=parser.parse_args()
    Path('data').mkdir(exist_ok=True)
    if args.export_calendar:
        from agent.interfaces.calendar_export import export
        print(f'{export(args.db or "data/agent.db",args.export_calendar)} compromissos exportados.')
        return
    if args.terminal:
        from agent.interfaces.terminal import run
    else:
        from agent.interfaces.whatsapp import run
    if args.db:
        run(args.db)
    else:
        run()


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        logging.getLogger('agent').error('falha_na_aplicacao\n%s', safe_traceback(error))
        raise SystemExit(1)
