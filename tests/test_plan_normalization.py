"""Plans observed in docs/transcricao-*.txt that used to be rejected and replanned."""
import json
import tempfile
import unittest
from pathlib import Path

from agent.application.conversation import parse_turn
from agent.application.planning import PlanError
from agent.bootstrap import build_app

TOOLS = {
    'agenda_criar': '{"titulo":"...","inicio":"AAAA-MM-DD HH:MM","fim":"AAAA-MM-DD HH:MM"}',
    'agenda_reagendar': '{"termo":"...","hora":"HH:MM","id":1,"revisao":0}',
    'financeiro_registrar': '{"tipo":"despesa","valor":"1,00","categoria":"outros","descricao":"..."}',
}


def turn(**plan):
    return json.dumps(plan)


class PlanNormalizationTests(unittest.TestCase):
    def test_question_without_tool_keeps_state(self):
        plan = parse_turn(turn(action='PERGUNTAR', context_action='CREATE_TASK',
                               message='O que você deseja marcar na sua agenda?'), TOOLS)
        self.assertEqual((plan['context_action'], plan.get('tool')), ('KEEP_TASK', None))

    def test_question_updating_without_active_task_keeps_state(self):
        plan = parse_turn(turn(action='PERGUNTAR', context_action='UPDATE_TASK',
                               message='Qual a descrição da despesa?'), TOOLS)
        self.assertEqual(plan['context_action'], 'KEEP_TASK')

    def test_fields_without_tool_are_still_rejected(self):
        with self.assertRaises(PlanError):
            parse_turn(turn(action='PERGUNTAR', context_action='CREATE_TASK', message='Qual o título?',
                            args={'hora': '09:00'}), TOOLS)

    def test_confirmation_with_update_or_create_reuses_preview(self):
        for transition, tool in (('UPDATE_TASK', 'agenda_criar'), ('CREATE_TASK', 'agenda_criar'),
                                 ('UPDATE_TASK', 'nenhuma')):
            plan = parse_turn(turn(action='CONFIRMAR', context_action=transition, tool=tool, message=''),
                              TOOLS, active_tool='agenda_criar', preview_tool='agenda_criar')
            self.assertEqual(plan['context_action'], 'KEEP_TASK')

    def test_confirmation_of_another_tool_or_task_is_rejected(self):
        with self.assertRaises(PlanError):
            parse_turn(turn(action='CONFIRMAR', context_action='CREATE_TASK', tool='financeiro_registrar',
                            message=''), TOOLS, active_tool='agenda_criar', preview_tool='agenda_criar')
        with self.assertRaises(PlanError):
            parse_turn(turn(action='CONFIRMAR', context_action='UPDATE_TASK', tool='agenda_criar',
                            message=''), TOOLS, active_tool='agenda_criar')
        with self.assertRaises(PlanError):
            parse_turn(turn(action='CONFIRMAR', context_action='RESUME_TASK', task_id=2, message=''),
                           TOOLS, active_tool='agenda_criar', preview_tool='agenda_criar', suspended_ids=[2])

    def test_update_of_another_tool_creates_task(self):
        for active in ('agenda_criar', None):
            plan = parse_turn(turn(action='EXECUTAR', context_action='UPDATE_TASK', tool='agenda_reagendar',
                                   args={'termo': 'palestra', 'hora': '10:00'}, message=''),
                              TOOLS, active_tool=active)
            self.assertEqual(plan['context_action'], 'CREATE_TASK')

    def test_completing_another_tool_creates_task(self):
        plan = parse_turn(turn(action='EXECUTAR', context_action='COMPLETE_TASK', tool='financeiro_registrar',
                               args={'valor': '50,00'}, message=''), TOOLS, active_tool='agenda_criar')
        self.assertEqual(plan['context_action'], 'CREATE_TASK')

    def test_update_of_active_tool_is_unchanged(self):
        plan = parse_turn(turn(action='PERGUNTAR', context_action='UPDATE_TASK', tool='agenda_criar',
                               args={'titulo': 'Aula'}, message='Qual a duração?'),
                          TOOLS, active_tool='agenda_criar')
        self.assertEqual(plan['context_action'], 'UPDATE_TASK')

    def test_question_with_fields_outside_create_or_update_is_rejected(self):
        # qwen2.5:3b, "Vamos agendar uma reunião?": invented fields that SUSPEND_TASK never stores.
        for transition, active in (('SUSPEND_TASK', 'agenda_criar'), ('CANCEL_TASK', 'agenda_criar'),
                                   ('KEEP_TASK', None), ('KEEP_TASK', 'financeiro_registrar')):
            with self.assertRaises(PlanError):
                parse_turn(turn(action='PERGUNTAR', context_action=transition, tool='agenda_criar',
                                args={'titulo': 'Reunião de estudo', 'inicio': '2026-11-27 10:00'},
                                message='Agora, 2026-11-27T10:00-04:00 em America/Manaus.'),
                           TOOLS, active_tool=active)

    def test_question_keeping_active_task_with_its_fields_updates_it(self):
        plan = parse_turn(turn(action='PERGUNTAR', context_action='KEEP_TASK', tool='agenda_criar',
                               args={'titulo': 'Aula'}, message='Qual a duração?'),
                          TOOLS, active_tool='agenda_criar')
        self.assertEqual(plan['context_action'], 'UPDATE_TASK')

    def test_first_question_reaches_user_with_one_model_call(self):
        calls = []

        def model(messages, schema):
            calls.append(messages)
            return turn(action='PERGUNTAR', context_action='CREATE_TASK',
                        message='O que você deseja marcar na sua agenda?')

        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', model)
            app.handle('owner', 'Quero marcar algo na minha agenda.')
            replies = []
            app.flush(lambda _, reply: replies.append(reply))
        self.assertEqual(len(calls), 1)
        self.assertEqual(replies, ['O que você deseja marcar na sua agenda?'])


if __name__ == '__main__':
    unittest.main()
