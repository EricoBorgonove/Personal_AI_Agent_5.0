import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

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
