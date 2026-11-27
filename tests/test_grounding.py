import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from agent.application.grounding import Evidence, ungrounded_fields
from agent.application.responses import ungrounded_moments
from agent.bootstrap import build_app

TODAY = date(2026, 11, 26)


class GroundingTests(unittest.TestCase):
    def test_invented_meeting_from_whatsapp_is_rejected(self):
        message = ('Aqui está a solicitação de reunião. Você gostaria de agendar uma reunião de estudo '
                   'para 10:00 do dia 27 de novembro?')
        self.assertTrue(ungrounded_moments(message, 'Vamos agendar uma reunião?', TODAY))
        self.assertTrue(ungrounded_moments('Agora, 2026-11-27T10:00-04:00 em America/Manaus.',
                                           'Vamos agendar uma reunião?', TODAY))

    def test_times_and_dates_from_the_conversation_are_accepted(self):
        cases = [
            ('Confirma amanhã, 27/11, às 9h?', 'Amanhã às 9.'),
            ('Qual a duração da aula de 28 de novembro às 09:30?', 'depois de amanhã às nove e meia {"hora": "09:30"}'),
            ('A palestra das 10:00 é a correta?', '[{"title": "Palestra", "start": "2026-11-27 10:00"}]'),
            ('Qual o título do compromisso de 2026-12-10?', 'Quero marcar algo em 2026-12-10.'),
            ('Qual horário? Pode informar, por exemplo, “15h” ou “15:30”.', 'Amanhã.'),
            ('Qual é o assunto da reunião?', 'Vamos agendar uma reunião?'),
        ]
        for message, evidence in cases:
            self.assertFalse(ungrounded_moments(message, evidence, TODAY), message)

    def test_relative_day_only_grounds_its_own_date(self):
        self.assertTrue(ungrounded_moments('Fica para 28/11?', 'Amanhã às 9.', TODAY))
        self.assertTrue(ungrounded_moments('Às 9h30?', 'Amanhã às 9.', TODAY))

    def fields(self, fields, speech, records='', tool='agenda_criar'):
        return ungrounded_fields(tool, fields, Evidence(speech, records, TODAY))

    def test_spoken_times_dates_and_durations_from_transcripts(self):
        cases = [
            ({'data': '2026-11-27', 'hora': '09:00'}, 'Amanhã às 9.'),
            ({'data': '2026-11-28', 'hora': '09:30'}, 'Depois de amanhã às nove e meia.'),
            ({'hora': '15:00'}, 'Às três da tarde.'),
            ({'hora': '21:00'}, 'Às vinte e uma horas.'),
            ({'hora': '12:00'}, 'Ao meio-dia.'),
            ({'minutos': 50}, 'Cinquenta minutos.'),
            ({'minutos': 90}, 'Uma hora e meia.'),
            ({'minutos': 120}, 'Duas horas.'),
            ({'minutos': 30}, 'Meia hora.'),
            ({'data': '2026-11-27'}, 'Na sexta.'),
            ({'data': '2026-12-05'}, 'No dia 5.'),
            ({'inicio': '2026-11-27 14:00', 'fim': '2026-11-27 16:00'}, 'Aula em 2026-11-27 das 14:00 às 16:00.'),
        ]
        for fields, speech in cases:
            self.assertEqual(self.fields(fields, speech), [], speech)

    def test_invented_values_are_reported(self):
        # qwen3:8b on "Vamos agendar uma reunião?": a made-up 15:00-16:00 slot.
        self.assertEqual(self.fields({'inicio': '2026-11-27 15:00', 'fim': '2026-11-27 16:00'},
                                     'Vamos agendar uma reunião?'), ['inicio', 'fim'])
        self.assertEqual(self.fields({'hora': '09:30'}, 'Amanhã às 9.'), ['hora'])
        self.assertEqual(self.fields({'minutos': 60}, 'Uma palestra de inteligência artificial.'), ['minutos'])
        self.assertEqual(self.fields({'data': '2026-11-27'}, 'Marque uma revisão.'), ['data'])

    def test_end_from_a_spoken_duration_is_grounded(self):
        stored = {'titulo': 'Palestra', 'data': '2026-11-28', 'hora': '09:00'}
        evidence = Evidence('Cinquenta minutos.', json.dumps(stored), TODAY)
        self.assertEqual(ungrounded_fields('agenda_criar', {'fim': '2026-11-28 09:50'}, evidence, stored), [])
        self.assertEqual(ungrounded_fields('agenda_criar', {'fim_hora': '09:50'}, evidence, stored), [])
        self.assertEqual(ungrounded_fields('agenda_criar', {'fim': '2026-11-28 10:00'}, evidence, stored), ['fim'])

    def test_invented_duration_is_dropped_and_title_is_kept(self):
        from datetime import datetime
        from agent.application.dialogue import DialogueManager
        from agent.application.working_memory import WorkingMemoryManager
        from agent.domain.policies import TZ

        class Store:
            def load(self, *_):
                return None

        memory = WorkingMemoryManager(Store(), 'owner', 'pessoal')
        memory.create('agenda_criar', {'data': '2026-11-27', 'hora': '09:00'})
        plan = {'action': 'PERGUNTAR', 'context_action': 'UPDATE_TASK', 'tool': 'agenda_criar',
                'args': {'titulo': 'Palestra de IA', 'minutos': 60}}
        DialogueManager().apply(memory, plan, datetime(2026, 11, 26, 20, 0, tzinfo=TZ),
                                Evidence('Uma palestra de IA.', json.dumps(memory.data), TODAY))
        self.assertEqual(memory.active['fields'], {'data': '2026-11-27', 'hora': '09:00', 'titulo': 'Palestra de IA'})

    def test_article_and_stored_digits_do_not_ground_hours(self):
        self.assertEqual(self.fields({'hora': '13:00'}, 'Quero uma reunião.'), ['hora'])
        records = 'id: 1 · valor brl: 120.00 · vencimento: 2026-12-10 {"valor": "85,90"}'
        self.assertEqual(self.fields({'hora': '10:00'}, 'Vamos agendar uma reunião?', records), ['hora'])

    def test_records_ground_exact_values(self):
        records = '[{"title": "Palestra", "start": "2026-11-27 09:00"}] Você confirma às 15h?'
        self.assertEqual(self.fields({'data': '2026-11-27', 'hora': '15:00'}, 'Isso.', records), [])

    def test_only_calendar_and_meeting_tools_are_checked(self):
        self.assertEqual(self.fields({'data': '2026-11-26'}, 'Gastei 30 reais.', tool='financeiro_registrar'), [])

    def test_offset_start_requires_a_spoken_duration(self):
        from datetime import datetime
        from agent.application.dialogue import DialogueManager
        from agent.application.planning import PlanError
        from agent.domain.policies import TZ

        class Memory:
            active = None
            data = {'active': None, 'suspended': []}

            def create(self, tool, fields):
                self.active = {'tool': tool, 'fields': fields}

        plan = {'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK', 'tool': 'agenda_criar',
                'args': {'titulo': 'Ligação', 'inicio_offset_minutos': 120}}
        current = datetime(2026, 11, 26, 10, 0, tzinfo=TZ)
        fields = DialogueManager().apply(Memory(), dict(plan, args=dict(plan['args'])), current,
                                         Evidence('Daqui a duas horas.', today=TODAY))
        self.assertEqual((fields['data'], fields['hora']), ('2026-11-26', '12:00'))
        with self.assertRaises(PlanError):
            DialogueManager().apply(Memory(), dict(plan, args=dict(plan['args'])), current,
                                    Evidence('Marque uma ligação.', today=TODAY))

    def test_orchestrator_rejects_invented_calendar_fields(self):
        plans = [
            {'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK', 'tool': 'agenda_criar',
             'args': {'titulo': 'Reunião', 'inicio': '2099-11-27 15:00', 'fim': '2099-11-27 16:00'},
             'message': 'Você deseja agendar uma reunião às 15h?'},
            {'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK', 'tool': 'agenda_criar',
             'args': {'titulo': 'Reunião'}, 'message': 'Para qual dia e horário?'},
        ]
        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', lambda *_: json.dumps(plans.pop(0)))
            app.handle('owner', 'Vamos agendar uma reunião?')
            replies = []
            app.flush(lambda _, reply: replies.append(reply))
            with app.uow.connection() as db:
                state = app.working_memory_repository(db).load('owner', 'pessoal').slots
        self.assertEqual(replies, ['Para qual dia e horário?'])
        self.assertEqual(state['active']['fields'], {'titulo': 'Reunião'})

    def test_orchestrator_replans_an_invented_time(self):
        plans = [
            {'action': 'PERGUNTAR', 'context_action': 'KEEP_TASK',
             'message': 'Você gostaria de uma reunião de estudo para 10:00 do dia 27 de novembro?'},
            {'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK', 'tool': 'agenda_criar', 'args': {},
             'message': 'Qual o assunto, o dia e o horário da reunião?'},
        ]
        prompts = []

        def model(messages, schema):
            prompts.append(messages[0]['content'])
            return json.dumps(plans.pop(0))

        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', model)
            app.handle('owner', 'Vamos agendar uma reunião?')
            replies = []
            app.flush(lambda _, reply: replies.append(reply))
        self.assertEqual(replies, ['Qual o assunto, o dia e o horário da reunião?'])
        self.assertIn('data_ou_horario_sem_origem_na_conversa', prompts[-1])


if __name__ == '__main__':
    unittest.main()
