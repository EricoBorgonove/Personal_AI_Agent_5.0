import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

from agent.bootstrap import build_app
from agent.domain.policies import now


class MemoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(tmp) / 'integration.db'
        self.model_calls = []
        self.app = build_app(self.path, 'owner', self.model)

    def model(self, messages, schema):
        self.model_calls.append(messages)
        return json.dumps({'action': 'RESPONDER', 'message': 'Estou à disposição.'})

    def say(self, text, sender='owner', event=None):
        self.app.handle(sender, text, event)
        replies = []
        self.app.flush(lambda _, message: replies.append(message))
        return '\n'.join(replies)

    def count(self, table):
        with self.app.uow.connection() as db:
            return db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

    def test_agenda_interruption_restart_and_exact_once(self):
        self.assertIn('Qual é a data?', self.say('Guarde na minha agenda uma palestra'))
        self.assertIn('Qual será a duração?', self.say('Amanhã às 14h.'))
        self.say('Como você pode me ajudar?')
        self.assertEqual(len(self.model_calls), 1)
        self.app = build_app(self.path, 'owner', self.model)
        self.assertIn('palestra', self.say('/contexto'))
        self.assertIn('14:50', self.say('50 minutos.'))
        self.assertEqual(self.count('calendar_events'), 0)
        self.assertNotIn('palestra', self.say('/contexto', 'guest'))
        self.say('Confirmo o compromisso.', 'guest')
        self.assertEqual(self.count('calendar_events'), 0)
        self.assertIn('registrado', self.say('Confirmo o compromisso.', event='confirm'))
        self.assertEqual(self.say('Confirmo o compromisso.', event='confirm'), '')
        self.say('Confirmo o compromisso.')
        self.assertEqual(self.count('calendar_events'), 1)

    def test_financial_drafts_are_confirmed_separately(self):
        self.assertIn('descrição', self.say('Registre uma despesa'))
        for step in ('Almoço', '34,50', 'alimentação'):
            reply = self.say(step)
        self.assertIn('Confirmo o lançamento', reply)
        self.assertEqual(self.count('finance_entries'), 0)
        self.say('Confirmo o lançamento.')
        self.say('Confirmo o lançamento.')
        self.assertEqual(self.count('finance_entries'), 1)

    def test_new_conversation_isolates_model_history_without_deleting_it(self):
        self.say('Como funciona o atendimento antigo?')
        self.say('Guarde na minha agenda uma palestra')
        self.say('/novaconversa')
        self.assertIn('Nenhum', self.say('/contexto'))
        self.say('Como funciona o atendimento agora?')
        self.assertFalse(any('atendimento antigo' in m['content'] for m in self.model_calls[-1]))
        self.assertGreater(self.count('messages'), 0)

    def test_task_uses_confirmation_and_cancel_only_clears_draft(self):
        self.assertIn('descrição da tarefa', self.say('Crie uma tarefa'))
        self.assertIn('Confirmo a tarefa', self.say('Revisar relatório'))
        self.say('/cancelar')
        self.assertIn('Nenhum', self.say('Confirmo a tarefa.'))
        self.assertEqual(self.count('tasks'), 0)
        self.say('Crie uma tarefa')
        self.say('Revisar relatório')
        self.say('Confirmo a tarefa')
        self.assertEqual(self.count('tasks'), 1)

    def test_card_installment_and_payable_use_existing_contracts(self):
        first = now().date() + timedelta(days=45)
        self.say('Cadastre um cartão')
        for text in ('Cartão didático', '1500', '5', str(first.day), 'Confirmo o cartão'):
            self.say(text)
        self.assertEqual(self.count('finance_cards'), 1)
        self.say('Registre uma compra parcelada')
        for text in ('#1', 'Livro', 'compras', '60', '3', first.isoformat(), 'Confirmo a compra parcelada'):
            self.say(text)
        self.assertEqual(self.count('finance_obligations'), 3)
        self.say('Registre uma conta a pagar')
        for text in ('Internet', '95,50', 'serviços', first.isoformat(), 'Confirmo a conta'):
            self.say(text)
        self.assertEqual(self.count('finance_obligations'), 4)
        self.assertEqual(self.count('finance_entries'), 0)

    def test_failure_to_complete_draft_rolls_back_existing_tool(self):
        for text in ('Guarde na minha agenda uma palestra', 'Amanhã às 14h', '50 minutos'):
            self.say(text)
        with self.app.uow.transaction() as db:
            db.execute("""CREATE TRIGGER block_draft_delete BEFORE DELETE ON working_memory_v1
                          BEGIN SELECT RAISE(ABORT, 'falha de teste'); END""")
        with self.assertLogs('agent.application.orchestrator', level='ERROR'):
            self.assertIn('rascunho continua', self.say('Confirmo o compromisso'))
        self.assertEqual(self.count('calendar_events'), 0)
        self.assertIn('14:50', self.say('/contexto'))
        with self.app.uow.transaction() as db:
            db.execute('DROP TRIGGER block_draft_delete')
        self.say('Confirmo o compromisso')
        self.assertEqual(self.count('calendar_events'), 1)

    def test_two_events_confirm_one_draft_only_once(self):
        for text in ('Guarde na minha agenda uma palestra', 'Amanhã às 14h', '50 minutos'):
            self.say(text)
        gate = Barrier(2)

        def confirm(event):
            gate.wait(timeout=10)
            self.app.handle('owner', 'Confirmo o compromisso.', event)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(confirm, ('confirmation-a', 'confirmation-b')))
        self.assertEqual(self.count('calendar_events'), 1)
        replies = []
        self.app.flush(lambda _, message: replies.append(message))
        self.assertEqual(sum('Compromisso registrado.' in reply for reply in replies), 1)
