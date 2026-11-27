import logging
import os
import threading

from agent.application.identity import IdentityResolver, LID_SERVER, jid_server, normalize_jid
from agent.bootstrap import build_app
from agent.diagnostics import safe_traceback

logger = logging.getLogger(__name__)


def event_jid(jid):
    if jid is None or getattr(jid, 'IsEmpty', False):
        return None
    return normalize_jid(f'{jid.User}@{jid.Server}')


def lookup_alternate(client, sender):
    from neonize.utils.jid import JIDToNonAD

    try:
        account = JIDToNonAD(sender)
        if account.Server == LID_SERVER:
            linked = client.get_pn_from_lid(account)
        else:
            linked = client.get_lid_from_pn(account)
    except Exception as error:
        logger.warning('consulta_alias_falhou\n%s', safe_traceback(error))
        return None
    return event_jid(linked)


def mask_jid(value):
    if value is None:
        return '-'
    user, server = value.split('@', 1)
    suffix = user[-4:] if len(user) > 4 else ''
    return f'***{suffix}@{server}'


def dispatch_message(app, client, source, text, event_id, resolver, *, debug=False, display_name=None):
    if source.IsFromMe or source.IsGroup or not text.strip():
        return False
    chat = event_jid(source.Chat)
    sender = event_jid(source.Sender)
    if sender is None or sender != chat:
        return False
    alternate = event_jid(getattr(source, 'SenderAlt', None))
    identity = resolver.resolve(sender, alternate, lambda: lookup_alternate(client, source.Sender))
    if debug:
        agent = app.factory.select(identity.principal)
        logger.info(
            '[IDENTITY] recebido=%s servidor=%s alternativo=%s vinculo=%s '
            'owner=%s owner_lid=%s comparacao=%s agente=%s acesso=%s',
            mask_jid(identity.sender), jid_server(identity.sender), mask_jid(alternate),
            mask_jid(identity.alternate), mask_jid(resolver.owner_jid), mask_jid(resolver.owner_lid),
            identity.matched_by, type(agent).__name__, 'privado' if agent.permits(True) else 'restrito',
        )
    app.handle(identity.principal, text.strip(), event_id, reply_to=chat,
               presentation_keys=identity.presentation_keys, display_name=display_name)
    return True


def run(path='data/agent.db'):
    from neonize.client import NewClient
    from neonize.events import MessageEv, ConnectedEv, DisconnectedEv
    from neonize import extract_text
    from neonize.utils.jid import build_jid

    try:
        resolver = IdentityResolver(os.getenv('OWNER_JID', ''), os.getenv('OWNER_LID', ''))
    except ValueError as error:
        raise SystemExit(str(error)) from None
    debug = os.getenv('DEBUG', '').strip().casefold() == 'true'

    # Native Neonize/Whatsmeow log payloads can contain identifiers and session data.
    for name in ('neonize', 'whatsmeow', 'Whatsmeow'):
        backend = logging.getLogger(name)
        backend.addHandler(logging.NullHandler())
        backend.propagate = False

    app = build_app(path, resolver.owner_jid)
    client = NewClient('data/sessao_whatsapp.db')
    lock = threading.RLock()
    connected = threading.Event()
    stopped = threading.Event()
    logger.info('transporte_iniciado tipo_owner=%s', jid_server(resolver.owner_jid))

    def send(to, message):
        user, server = to.split('@', 1)
        client.send_message(build_jid(user, server=server), message)

    @client.event(ConnectedEv)
    def on_connect(c, event):
        connected.set()
        logger.info('whatsapp_conectado')

    @client.event(DisconnectedEv)
    def on_disconnect(c, event):
        connected.clear()
        logger.warning('whatsapp_desconectado')

    @client.event(MessageEv)
    def on_message(c, event):
        try:
            with lock:
                source = event.Info.MessageSource
                text = extract_text(event.Message) or ''
                if dispatch_message(app, c, source, text, str(event.Info.ID), resolver, debug=debug,
                                    display_name=getattr(event.Info, 'PushName', None)):
                    app.flush(send)
        except Exception as error:
            logger.error('evento_whatsapp_falhou\n%s', safe_traceback(error))

    def retry():
        while not stopped.wait(5):
            if connected.is_set():
                with lock:
                    for operation in (app.enqueue_finance_reminders, app.enqueue_calendar_reminders):
                        try:
                            operation()
                        except Exception as error:
                            logger.error('lembrete_falhou tipo=%s\n%s',
                                         operation.__name__, safe_traceback(error))
                    try:
                        app.flush(send)
                    except Exception as error:
                        logger.error('outbox_falhou\n%s', safe_traceback(error))

    threading.Thread(target=retry, daemon=True).start()
    try:
        client.connect()
    finally:
        stopped.set()
