import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from agent.bootstrap import build_app
from agent.domain.policies import now


class DialogueTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(tmp) / 'test.db'
        self.app = build_app(self.path, 'owner', self.no_model)

    def no_model(self, *_):
        self.fail('A conversa determinística chamou o Ollama')

    def say(self, text, sender='guest', event=None):
        self.app.handle(sender, text, event)
        replies = []
        self.app.flush(lambda to, reply: replies.append((to, reply)))
        return replies

    def count(self, table):
        with self.app.uow.connection() as db:
            return db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

    def test_greeting_and_informal_request_to_talk(self):
        self.assertIn('Olá', self.say('Olá.')[0][1])
        self.assertIn('conversar', self.say('Precisamos conversar.')[0][1])
        self.assertEqual(self.count('requests'), 0)

    def test_meeting_fields_persist_across_restarts_and_are_separate(self):
        self.assertIn('assunto', self.say('Podemos marcar uma reunião?')[0][1])
        self.assertIn('dia', self.say('Orientação de TCC.')[0][1])
        self.assertIn('assunto', self.say('Quero marcar uma reunião.', 'other')[0][1])
        self.app = build_app(self.path, 'owner', self.no_model)
        self.assertIn('horário', self.say('Amanhã.')[0][1])
        self.assertEqual(self.count('requests'), 0)
        replies = self.say('Às 15h.', event='last')
        self.assertEqual([to for to, _ in replies], ['owner', 'guest'])
        self.assertIn('aprovação', replies[-1][1])
        self.assertIn('60 minutos', replies[-1][1])
        self.assertEqual(self.say('Às 15h.', event='last'), [])
        self.assertEqual(self.count('requests'), 1)
        self.assertEqual(self.count('calendar_events'), 0)
        self.assertIn('dia', self.say('Planejamento', 'other')[0][1])

    def test_explicit_duration_is_preserved_when_owner_confirms(self):
        start = (now()+timedelta(days=2)).date().isoformat()
        self.say(f'Quero marcar uma reunião. Assunto: TCC. Data: {start} 15:00. Duração: 30 minutos.')
        self.assertIn('não permitida', self.say('Confirmo a reunião #1')[0][1])
        self.assertEqual(self.count('calendar_events'), 0)
        self.say('Confirmo a reunião #1', 'owner')
        with self.app.uow.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT start,end FROM calendar_events').fetchone()),
                             (f'{start} 15:00', f'{start} 15:30'))

    def test_date_given_in_meeting_invitation_is_not_used_as_subject(self):
        self.assertIn('assunto', self.say('Podemos marcar uma reunião para amanhã às 15h?')[0][1])
        self.assertEqual(self.count('requests'), 0)
        self.assertIn('aprovação', self.say('Orientação de TCC.')[-1][1])

    def test_negated_meeting_and_unavailable_times_do_not_register(self):
        self.say('Não marque uma reunião. Assunto: TCC. Amanhã às 15h.')
        self.assertIn('dia', self.say('Quero marcar uma reunião. Assunto: TCC.')[0][1])
        self.assertIn('dia', self.say('Não posso amanhã às 15h.')[0][1])
        self.assertEqual(self.count('requests'), 0)

    def test_configured_duration_is_reported_to_both_parties(self):
        self.app = build_app(self.path, 'owner', self.no_model, meeting_duration=45)
        replies = self.say('Quero solicitar reunião. Assunto: TCC. Amanhã às 15h.')
        self.assertIn('45 min', replies[0][1])
        self.assertIn('45 minutos', replies[-1][1])

    def test_invalid_owner_counterproposal_has_user_facing_date_error(self):
        self.say('Quero solicitar reunião. Assunto: TCC. Amanhã às 15h.')
        response = self.say('Proponho #1 2090-02-31 15:00', 'owner')[0][1]
        self.assertIn('data e um horário válidos', response)
        self.assertNotIn('out of range', response)

    def test_progressive_note_uses_only_text_from_contact(self):
        self.assertIn('Qual recado', self.say('Posso deixar um recado pro professor?')[0][1])
        self.assertEqual(self.count('notes'), 0)
        replies = self.say('O documento está pronto.')
        self.assertEqual([to for to, _ in replies], ['owner', 'guest'])
        self.assertEqual(self.count('notes'), 1)

    def test_unsupported_financial_value_does_not_reach_executor(self):
        self.app = build_app(self.path, 'owner', lambda *_: (
            '{"action":"EXECUTAR","tool":"financeiro_registrar","args":'
            '{"tipo":"despesa","descricao":"Almoço","categoria":"alimentacao","valor":"40,00"}}'
        ))
        self.assertIn('o valor', self.say('Registre uma despesa de almoço.', 'owner')[0][1])
        self.assertEqual(self.count('finance_entries'), 0)

    def test_unsupported_calendar_time_does_not_reach_executor(self):
        day = (now()+timedelta(days=2)).date().isoformat()
        self.app = build_app(self.path, 'owner', lambda *_: (
            '{"action":"EXECUTAR","tool":"agenda_criar","args":'
            f'{{"titulo":"Revisão","inicio":"{day} 09:00","fim":"{day} 10:00"}}}}'
        ))
        reply = self.say(f'Crie um compromisso na agenda no dia {day}.', 'owner')[0][1]
        self.assertIn('horário', reply)
        self.assertNotIn('09:00', reply)
        self.assertEqual(self.count('calendar_events'), 0)

    def test_model_cannot_invent_a_meeting_or_publish_its_planner_messages(self):
        payloads = iter((
            '{"action":"EXECUTAR","tool":"solicitar_reuniao","args":{"nome":"Fictício","horario":"2099-01-01 09:00","assunto":"TCC"}}',
            '{"action":"RESPONDER","message":"O plano anterior foi rejeitado. A reunião será marcada amanhã às 09:00."}',
        ))
        self.app = build_app(self.path, 'owner', lambda *_: next(payloads))
        reply = self.say('Você tem informações para me passar?')[0][1]
        self.assertNotIn('plano', reply.lower())
        self.assertNotIn('09:00', reply)
        self.assertEqual(self.count('requests'), 0)

    def test_invalid_ollama_json_has_safe_reply(self):
        self.app = build_app(self.path, 'owner', lambda *_: '{invalid')
        reply = self.say('Você pode consultar a documentação pública?')[0][1]
        self.assertNotIn('json', reply.lower())
        self.assertEqual(self.count('requests'), 0)
