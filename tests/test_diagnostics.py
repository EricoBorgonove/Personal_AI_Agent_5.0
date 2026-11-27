import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.bootstrap import build_app
from agent.infrastructure.ollama import ask_ollama


class OrchestrationDiagnosticsTests(unittest.TestCase):
    def test_invalid_tool_is_replanned_with_role_specific_schema(self):
        attempts = iter(('ferramenta_inexistente', 'final'))

        def model(messages, schema):
            allowed = schema['properties']['tool'].get('enum', [])
            if 'final' not in allowed or 'criar_tarefa' in allowed:
                return '{"tool":"criar_tarefa","args":{},"response":""}'
            return json.dumps({'tool': next(attempts), 'args': {}, 'response': 'Olá!'})

        with tempfile.TemporaryDirectory() as tmp:
            app = build_app(Path(tmp) / 'test.db', 'owner', model)
            app.handle('guest', 'Olá!')
            replies = []
            app.flush(lambda _, message: replies.append(message))

        self.assertEqual(replies, ['Assistente virtual: Olá!'])

    def test_repeated_mutation_is_not_executed_again(self):
        call = '{"tool":"criar_tarefa","args":{"texto":"Revisar relatório"},"response":""}'
        calls = iter((call, call))

        def model(messages, schema):
            if schema['properties']['tool'].get('enum') == ['final']:
                return '{"tool":"final","args":{},"response":"Tarefa registrada."}'
            return next(calls)

        with tempfile.TemporaryDirectory() as tmp:
            app = build_app(Path(tmp) / 'test.db', 'owner', model)
            app.handle('owner', 'Crie a tarefa Revisar relatório.')
            with app.uow.connection() as db:
                tasks = db.execute('SELECT text FROM tasks').fetchall()
            replies = []
            app.flush(lambda _, message: replies.append(message))

        self.assertEqual([task['text'] for task in tasks], ['Revisar relatório'])
        self.assertEqual(replies, ['Tarefa registrada.'])

    def test_unexpected_tool_failure_keeps_traceback_and_hides_exception_data(self):
        def explode():
            raise RuntimeError('dado confidencial de teste')

        knowledge = SimpleNamespace(search=lambda *_: explode())
        plan = '{"tool":"rag_publico","args":{"busca":"consulta privada"},"response":""}'
        with tempfile.TemporaryDirectory() as tmp:
            app = build_app(Path(tmp) / 'test.db', 'owner', lambda *_: plan, knowledge)
            with self.assertLogs('agent.application', level='ERROR') as logs:
                app.handle('guest', 'mensagem privada')
        output = '\n'.join(logs.output)
        self.assertIn('Traceback', output)
        self.assertIn('explode', output)
        self.assertIn('RuntimeError', output)
        for private in ('dado confidencial de teste', 'consulta privada', 'mensagem privada'):
            self.assertNotIn(private, output)

    def test_invalid_tool_result_rolls_back_sqlite_changes(self):
        from agent.infrastructure.repositories import Repository

        class InvalidResultRepository(Repository):
            def create_task(self, text):
                super().create_task(text)
                return object()

        def model(messages, schema):
            if schema['properties']['tool']['enum'] == ['final']:
                return '{"tool":"final","args":{},"response":"Só preciso que confirme os dados."}'
            return '{"tool":"criar_tarefa","args":{"texto":"Ação"},"response":""}'

        with tempfile.TemporaryDirectory() as tmp:
            app = build_app(Path(tmp) / 'test.db', 'owner', model)
            app.repository = InvalidResultRepository
            with self.assertLogs('agent.application.orchestrator', level='ERROR') as logs:
                app.handle('owner', 'Crie a tarefa Ação.')
            with app.uow.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
        self.assertIn('etapa_revertida', '\n'.join(logs.output))


class OllamaDiagnosticsTests(unittest.TestCase):
    def test_rejects_truncated_content_even_if_it_is_valid_json(self):
        body = json.dumps({'done': True, 'done_reason': 'length',
                           'message': {'content': '{"tool":"final"}'}}).encode('utf-8')
        with patch('urllib.request.urlopen', return_value=io.BytesIO(body)):
            with self.assertRaisesRegex(ValueError, 'truncada'):
                ask_ollama([])

    def test_uses_utf8_for_request_and_response(self):
        body = '{"done":true,"message":{"content":"Olá, João!"}}'.encode('utf-8')

        def endpoint(request, timeout):
            self.assertIn('Ação'.encode('utf-8'), request.data)
            return io.BytesIO(body)

        with patch('urllib.request.urlopen', side_effect=endpoint):
            self.assertEqual(ask_ollama([{'role': 'user', 'content': 'Ação'}]), 'Olá, João!')


class WhatsAppDiagnosticsTests(unittest.TestCase):
    def test_owner_alias_uses_configured_identity_and_routes_reply_to_chat(self):
        from neonize.proto.Neonize_pb2 import MessageSource
        from neonize.utils.jid import build_jid
        from agent.application.identity import IdentityResolver
        from agent.interfaces import whatsapp

        chat = build_jid('200', server='lid')
        owner = build_jid('100')
        source = MessageSource(Chat=chat, Sender=chat, SenderAlt=owner)
        direct = MessageSource(Chat=owner, Sender=owner)
        plan = '{"tool":"criar_tarefa","args":{"texto":"Ação"},"response":""}'
        responses = iter((plan, '{"tool":"final","args":{},"response":"Tarefa registrada."}'))
        with tempfile.TemporaryDirectory() as tmp:
            app = build_app(Path(tmp) / 'test.db', '100@s.whatsapp.net', lambda *_: next(responses))
            resolver = IdentityResolver('100@s.whatsapp.net')
            whatsapp.dispatch_message(app, object(), source, 'Olá!', 'event', resolver)
            whatsapp.dispatch_message(app, object(), direct, 'Olá!', 'event', resolver)
            replies = []
            app.flush(lambda to, reply: replies.append((to, reply)))
            with app.uow.connection() as db:
                tasks = db.execute('SELECT text FROM tasks').fetchall()
        self.assertEqual([task['text'] for task in tasks], ['Ação'])
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[-1], ('200@lid', 'Tarefa registrada.'))

    def test_owner_configured_as_lid_resolves_through_neonize_store(self):
        from neonize.proto.Neonize_pb2 import MessageSource
        from neonize.utils.jid import build_jid
        from agent.application.identity import IdentityResolver
        from agent.interfaces.whatsapp import dispatch_message

        chat = build_jid('100')
        chat.Device = 2
        source = MessageSource(Chat=chat, Sender=chat)

        def lookup(account):
            self.assertEqual(account.Device, 0)
            return build_jid('200', server='lid')

        calls = []
        app = SimpleNamespace(handle=lambda sender, *_args, **_kwargs: calls.append(sender))
        resolver = IdentityResolver('200@lid')
        dispatch_message(app, SimpleNamespace(get_lid_from_pn=lookup), source, 'Olá!', 'event', resolver)
        self.assertEqual(calls, ['200@lid'])

    def test_equal_digits_without_verified_mapping_stay_social(self):
        from neonize.proto.Neonize_pb2 import JID, MessageSource
        from neonize.utils.jid import build_jid
        from agent.application.identity import IdentityResolver
        from agent.interfaces.whatsapp import dispatch_message

        chat = build_jid('100', server='lid')
        source = MessageSource(Chat=chat, Sender=chat)
        client = SimpleNamespace(get_pn_from_lid=lambda _: JID())
        calls = []
        app = SimpleNamespace(handle=lambda sender, *_args, **_kwargs: calls.append(sender))
        resolver = IdentityResolver('100@s.whatsapp.net')
        dispatch_message(app, client, source, 'Olá!', 'event', resolver)
        source.IsFromMe = True
        dispatch_message(app, client, source, 'Olá!', 'self', resolver)
        source.IsFromMe = False
        source.IsGroup = True
        dispatch_message(app, client, source, 'Olá!', 'group', resolver)
        self.assertEqual(calls, ['100@lid'])
