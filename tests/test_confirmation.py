import json
import tempfile
import unittest
from pathlib import Path

from agent.application.conversation import is_affirmation
from agent.bootstrap import build_app


class AffirmationTests(unittest.TestCase):
    def test_short_approvals(self):
        for text in ('Sim', 'sim!', 'Pode confirmar.', 'Isso mesmo.', 'OK', 'Tá certo', 'Está certo.',
                     'Confirmo', 'pode lançar', '👍', '  sim,  pode  '):
            self.assertTrue(is_affirmation(text), text)

    def test_corrections_and_other_requests_are_not_approvals(self):
        for text in ('Sim, mas às 10', 'Não', 'Não pode', 'Pode mudar para 50 minutos?',
                     'Confirmo a reunião #1', 'Confirme, mas com o texto Tarefa diferente.', 'Sim e não', ''):
            self.assertFalse(is_affirmation(text), text)


class DeterministicConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []
        self.plans = []

        def model(messages, schema):
            self.calls.append(messages[-1]['content'])
            return json.dumps(self.plans.pop(0))

        self.app = build_app(Path(self.directory.name) / 'agent.db', 'owner', model)

    def tearDown(self):
        self.directory.cleanup()

    def tasks(self):
        with self.app.uow.connection() as db:
            return [row[0] for row in db.execute('SELECT text FROM tasks')]

    def test_approval_executes_preview_without_model_call(self):
        self.plans = [{'action': 'EXECUTAR', 'context_action': 'CREATE_TASK', 'tool': 'criar_tarefa',
                       'args': {'texto': 'Revisar slides'}}]
        self.app.handle('owner', 'Crie a tarefa revisar slides.')
        self.app.handle('owner', 'Sim', 'e1')
        self.app.handle('owner', 'Sim', 'e1')
        self.assertEqual(self.calls, ['Crie a tarefa revisar slides.'])
        self.assertEqual(self.tasks(), ['Revisar slides'])
        with self.app.uow.connection() as db:
            self.assertIsNone(self.app.working_memory_repository(db).load('owner', 'pessoal'))

    def test_approval_without_preview_goes_to_model(self):
        self.plans = [{'action': 'RESPONDER', 'message': 'Não há nada para confirmar.'}]
        self.app.handle('owner', 'Sim')
        self.assertEqual(self.calls, ['Sim'])
        self.assertEqual(self.tasks(), [])

    def test_correction_goes_to_model_and_keeps_preview(self):
        self.plans = [
            {'action': 'EXECUTAR', 'context_action': 'CREATE_TASK', 'tool': 'criar_tarefa',
             'args': {'texto': 'Revisar slides'}},
            {'action': 'EXECUTAR', 'context_action': 'UPDATE_TASK', 'tool': 'criar_tarefa',
             'args': {'texto': 'Revisar slides da oficina'}},
        ]
        self.app.handle('owner', 'Crie a tarefa revisar slides.')
        self.app.handle('owner', 'Sim, mas é dos slides da oficina.')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.tasks(), [])
        self.app.handle('owner', 'Pode gravar.')
        self.assertEqual(self.tasks(), ['Revisar slides da oficina'])

    def test_external_contact_approval_only_creates_pending_request(self):
        from datetime import timedelta
        from agent.domain.policies import now

        slot = (now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
        self.plans = [{'action': 'EXECUTAR', 'context_action': 'CREATE_TASK', 'tool': 'solicitar_reuniao',
                       'args': {'nome': 'João', 'assunto': 'TCC', 'horario': slot}}]
        self.app.handle('aluno', 'Quero uma reunião sobre TCC.')
        self.app.handle('aluno', 'Pode confirmar.')
        with self.app.uow.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM requests').fetchone()[0], 'PENDENTE')
            self.assertEqual(db.execute('SELECT count(*) FROM calendar_events').fetchone()[0], 0)
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
