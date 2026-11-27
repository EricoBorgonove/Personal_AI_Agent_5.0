import json
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
        self.plans = {}
        self.app = build_app(self.path, 'owner', self.model)

    def model(self, messages, schema):
        return json.dumps(self.plans[messages[-1]['content']])

    def plan(self, text, action, tool=None, transition=None, message=None, **fields):
        plan = {'action': action}
        if tool:
            plan.update(tool=tool, args=fields)
        if transition:
            plan['context_action'] = transition
        if message:
            plan['message'] = message
        self.plans[text] = plan

    def meeting(self, request, *, day_offset=1, hour='15:00', **fields):
        self.plan(request, 'EXECUTAR', 'solicitar_reuniao', 'CREATE_TASK',
                  dia_offset=day_offset, hora=hour, assunto='TCC', **fields)
        self.say(request)
        self.plan('Pode confirmar.', 'CONFIRMAR')
        return self.say('Pode confirmar.')

    def say(self, text, sender='guest', event=None):
        self.app.handle(sender, text, event)
        replies = []
        self.app.flush(lambda to, reply: replies.append((to, reply)))
        return replies

    def count(self, table):
        with self.app.uow.connection() as db:
            return db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

    def test_greeting_and_informal_request_to_talk(self):
        self.plan('Olá.', 'RESPONDER', message='Olá! Como posso ajudar?')
        self.plan('Precisamos conversar.', 'RESPONDER', message='Claro, podemos conversar.')
        self.assertIn('Olá', self.say('Olá.')[0][1])
        self.assertIn('conversar', self.say('Precisamos conversar.')[0][1])
        self.assertEqual(self.count('requests'), 0)

    def test_meeting_fields_persist_across_restarts_and_are_separate(self):
        self.plan('Podemos marcar uma reunião?', 'PERGUNTAR', 'solicitar_reuniao', 'CREATE_TASK', 'Qual é o assunto?')
        self.plan('Orientação de TCC.', 'PERGUNTAR', 'solicitar_reuniao', 'UPDATE_TASK', 'Qual dia?', assunto='Orientação de TCC')
        self.plan('Quero marcar uma reunião.', 'PERGUNTAR', 'solicitar_reuniao', 'CREATE_TASK', 'Qual é o assunto?')
        self.plan('Amanhã.', 'PERGUNTAR', 'solicitar_reuniao', 'UPDATE_TASK', 'Qual horário?', dia_offset=1)
        self.plan('Às 15h.', 'EXECUTAR', 'solicitar_reuniao', 'UPDATE_TASK', hora='15:00')
        self.plan('Pode confirmar.', 'CONFIRMAR')
        self.plan('Planejamento', 'PERGUNTAR', 'solicitar_reuniao', 'UPDATE_TASK', 'Qual dia?', assunto='Planejamento')
        self.assertIn('assunto', self.say('Podemos marcar uma reunião?')[0][1])
        self.assertIn('dia', self.say('Orientação de TCC.')[0][1])
        self.assertIn('assunto', self.say('Quero marcar uma reunião.', 'other')[0][1])
        self.app = build_app(self.path, 'owner', self.model)
        self.assertIn('horário', self.say('Amanhã.')[0][1])
        self.assertEqual(self.count('requests'), 0)
        self.assertIn('Você confirma?', self.say('Às 15h.', event='last')[-1][1])
        replies = self.say('Pode confirmar.')
        self.assertEqual([to for to, _ in replies], ['owner', 'guest'])
        self.assertIn('aprovação', replies[-1][1])
        self.assertIn('60 minutos', replies[-1][1])
        self.assertEqual(self.say('Às 15h.', event='last'), [])
        self.assertEqual(self.count('requests'), 1)
        self.assertEqual(self.count('calendar_events'), 0)
        self.assertIn('dia', self.say('Planejamento', 'other')[0][1])

    def test_explicit_duration_is_preserved_when_owner_confirms(self):
        start = (now()+timedelta(days=2)).date().isoformat()
        self.meeting(f'Quero marcar uma reunião. Assunto: TCC. Data: {start} 15:00. Duração: 30 minutos.',
                     day_offset=2, duracao=30)
        self.assertIn('não permitida', self.say('Confirmo a reunião #1')[0][1])
        self.assertEqual(self.count('calendar_events'), 0)
        self.say('Confirmo a reunião #1', 'owner')
        with self.app.uow.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT start,end FROM calendar_events').fetchone()),
                             (f'{start} 15:00', f'{start} 15:30'))

    def test_date_given_in_meeting_invitation_is_not_used_as_subject(self):
        self.plan('Podemos marcar uma reunião para amanhã às 15h?', 'PERGUNTAR', 'solicitar_reuniao',
                  'CREATE_TASK', 'Qual é o assunto?', dia_offset=1, hora='15:00')
        self.plan('Orientação de TCC.', 'EXECUTAR', 'solicitar_reuniao', 'UPDATE_TASK', assunto='Orientação de TCC')
        self.plan('Pode confirmar.', 'CONFIRMAR')
        self.assertIn('assunto', self.say('Podemos marcar uma reunião para amanhã às 15h?')[0][1])
        self.assertEqual(self.count('requests'), 0)
        self.say('Orientação de TCC.')
        self.assertIn('aprovação', self.say('Pode confirmar.')[-1][1])

    def test_negated_meeting_and_unavailable_times_do_not_register(self):
        self.plan('Não marque uma reunião. Assunto: TCC. Amanhã às 15h.', 'RESPONDER', message='Entendido.')
        self.plan('Quero marcar uma reunião. Assunto: TCC.', 'PERGUNTAR', 'solicitar_reuniao',
                  'CREATE_TASK', 'Qual dia?', assunto='TCC')
        self.plan('Não posso amanhã às 15h.', 'PERGUNTAR', message='Qual outro dia serve?')
        self.say('Não marque uma reunião. Assunto: TCC. Amanhã às 15h.')
        self.assertIn('dia', self.say('Quero marcar uma reunião. Assunto: TCC.')[0][1])
        self.assertIn('dia', self.say('Não posso amanhã às 15h.')[0][1])
        self.assertEqual(self.count('requests'), 0)

    def test_configured_duration_is_reported_to_both_parties(self):
        self.app = build_app(self.path, 'owner', self.model, meeting_duration=45)
        replies = self.meeting('Quero solicitar reunião. Assunto: TCC. Amanhã às 15h.')
        self.assertIn('45 min', replies[0][1])
        self.assertIn('45 minutos', replies[-1][1])

    def test_invalid_owner_counterproposal_has_user_facing_date_error(self):
        self.meeting('Quero solicitar reunião. Assunto: TCC. Amanhã às 15h.')
        response = self.say('Proponho #1 2090-02-31 15:00', 'owner')[0][1]
        self.assertIn('data e um horário válidos', response)
        self.assertNotIn('out of range', response)

    def test_progressive_note_uses_only_text_from_contact(self):
        self.plan('Posso deixar um recado pro professor?', 'PERGUNTAR', 'registrar_recado',
                  'CREATE_TASK', 'Qual recado você gostaria de deixar?')
        self.plan('O documento está pronto.', 'EXECUTAR', 'registrar_recado', 'UPDATE_TASK',
                  texto='O documento está pronto.')
        self.plan('Pode confirmar.', 'CONFIRMAR')
        self.assertIn('Qual recado', self.say('Posso deixar um recado pro professor?')[0][1])
        self.assertEqual(self.count('notes'), 0)
        self.say('O documento está pronto.')
        self.assertEqual(self.count('notes'), 0)
        replies = self.say('Pode confirmar.')
        self.assertEqual([to for to, _ in replies], ['owner', 'guest'])
        self.assertEqual(self.count('notes'), 1)

    def test_unconfirmed_financial_value_does_not_reach_executor(self):
        self.app = build_app(self.path, 'owner', lambda *_: (
            '{"action":"EXECUTAR","tool":"financeiro_registrar","args":'
            '{"tipo":"despesa","descricao":"Almoço","categoria":"alimentacao","valor":"40,00"}}'
        ))
        self.assertIn('Você confirma?', self.say('Registre uma despesa de almoço.', 'owner')[0][1])
        self.assertEqual(self.count('finance_entries'), 0)

    def test_invented_calendar_time_does_not_reach_preview_or_executor(self):
        day = (now()+timedelta(days=2)).date().isoformat()
        self.app = build_app(self.path, 'owner', lambda *_: (
            '{"action":"EXECUTAR","tool":"agenda_criar","args":'
            f'{{"titulo":"Revisão","inicio":"{day} 09:00","fim":"{day} 10:00"}}}}'
        ))
        reply = self.say(f'Crie um compromisso na agenda no dia {day}.', 'owner')[0][1]
        self.assertNotIn('09:00', reply)
        self.assertEqual(self.count('calendar_events'), 0)
        reply = self.say(f'Crie a revisão no dia {day} das 09:00 às 10:00.', 'owner')[0][1]
        self.assertIn('Você confirma?', reply)
        self.assertEqual(self.count('calendar_events'), 0)

    def test_model_cannot_create_an_invented_meeting(self):
        proposal = ('{"action":"EXECUTAR","tool":"solicitar_reuniao","args":'
                    '{"nome":"Fictício","horario":"2099-01-01 09:00","assunto":"TCC"}}')
        self.app = build_app(self.path, 'owner', lambda *_: proposal)
        reply = self.say('Você tem informações para me passar?')[0][1]
        self.assertNotIn('plano', reply.lower())
        self.assertNotIn('2099', reply)
        self.assertEqual(self.count('requests'), 0)
        reply = self.say('Quero falar sobre TCC em 2099-01-01 09:00.')[0][1]
        self.assertIn('Você confirma?', reply)
        self.assertEqual(self.count('requests'), 0)

    def test_invalid_ollama_json_has_safe_reply(self):
        self.app = build_app(self.path, 'owner', lambda *_: '{invalid')
        reply = self.say('Você pode consultar a documentação pública?')[0][1]
        self.assertNotIn('json', reply.lower())
        self.assertEqual(self.count('requests'), 0)
