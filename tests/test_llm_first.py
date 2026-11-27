import json
import tempfile
import unittest
from pathlib import Path

from agent.bootstrap import build_app


class LLMFirstTests(unittest.TestCase):
    def test_stale_meeting_does_not_intercept_new_calendar_request(self):
        calls = []

        def model(messages, schema):
            calls.append(messages)
            return json.dumps({
                'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK',
                'tool': 'agenda_criar', 'args': {},
                'message': 'Que compromisso você quer marcar?',
            })

        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', model)
            with app.uow.transaction() as db:
                app.repository(db).save_dialogue('owner', {'kind': 'meeting', 'assunto': 'Palestra antiga'})
            app.handle('owner', 'Quero marcar algo na minha agenda.')
            self.assertEqual(len(calls), 1)
            replies = []
            app.flush(lambda _, message: replies.append(message))
            self.assertEqual(replies, ['Que compromisso você quer marcar?'])

    def test_structured_calendar_survives_restart_and_confirmation_is_idempotent(self):
        from agent.domain.policies import now
        from datetime import timedelta

        plans = iter([
            dict(action='PERGUNTAR', context_action='CREATE_TASK', tool='agenda_criar',
                 args={}, message='O que gostaria de marcar?'),
            dict(action='PERGUNTAR', context_action='UPDATE_TASK', tool='agenda_criar',
                 args={'dia_offset': 1, 'hora': '09:00'}, message='Qual o título e a duração?'),
            dict(action='PERGUNTAR', context_action='UPDATE_TASK', tool='agenda_criar',
                 args={'titulo': 'Palestra de inteligência artificial'}, message='Qual a duração?'),
            dict(action='EXECUTAR', context_action='UPDATE_TASK', tool='agenda_criar',
                 args={'minutos': 50}),
            dict(action='CONFIRMAR'),
        ])

        def model(messages, schema):
            plan = next(plans)
            if plan.get('args') == {'minutos': 50}:
                self.assertIn('"hora": "09:00"', messages[0]['content'])
                self.assertIn({'role': 'assistant', 'content': 'Qual a duração?'}, messages)
            return json.dumps(plan)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agent.db'
            app = build_app(path, 'owner', model)
            app.handle('owner', 'Quero marcar algo na minha agenda.')
            app.handle('owner', 'Amanhã às 9.')
            app.handle('owner', 'Uma palestra de inteligência artificial.')
            app = build_app(path, 'owner', model)
            app.handle('owner', 'Cinquenta minutos.')
            app.handle('owner', 'Pode confirmar.', 'confirmation')
            app.handle('owner', 'Pode confirmar.', 'confirmation')
            day = (now().date() + timedelta(days=1)).isoformat()
            with app.uow.connection() as db:
                self.assertEqual([tuple(row) for row in db.execute('SELECT title,start,end FROM calendar_events')],
                                 [('Palestra de inteligência artificial', f'{day} 09:00', f'{day} 09:50')])

    def test_two_senders_run_model_without_holding_write_transaction(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        gate = Barrier(2)

        def model(messages, schema):
            gate.wait(timeout=4)
            owner = 'agenda_criar' in schema['properties']['tool']['enum']
            self.assertEqual(owner, 'agenda' in messages[-1]['content'])
            return json.dumps({'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK',
                               'tool': 'agenda_criar' if owner else 'registrar_recado',
                               'message': 'Qual compromisso?' if owner else 'Qual recado?'})

        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', model)
            with ThreadPoolExecutor(max_workers=2) as pool:
                owner = pool.submit(app.handle, 'owner', 'Preciso da agenda')
                guest = pool.submit(app.handle, 'guest', 'Quero deixar um recado')
                owner.result()
                guest.result()
            with app.uow.connection() as db:
                for sender, role, expected in [('owner', 'pessoal', 'agenda_criar'),
                                                ('guest', 'social', 'registrar_recado')]:
                    draft = app.working_memory_repository(db).load(sender, role)
                    self.assertEqual(draft.slots['active']['tool'], expected)

    def test_invalid_json_retries_once_and_identical_reply_requests_replanning(self):
        plans = iter(['{invalid', '{"action":"PERGUNTAR","message":"Qual compromisso?"}',
                      '{"action":"PERGUNTAR","message":"Qual compromisso?"}',
                      '{"action":"PERGUNTAR","message":"Que título você quer usar?"}'])
        prompts = []

        def model(messages, schema):
            prompts.append(messages[0]['content'])
            return next(plans)

        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', model)
            app.handle('owner', 'Quero agendar.')
            app.handle('owner', 'Amanhã.')
            replies = []
            app.flush(lambda _, reply: replies.append(reply))
            self.assertEqual(replies, ['Qual compromisso?', 'Que título você quer usar?'])
            self.assertIn('pergunta_sem_progresso', prompts[-1])

    def test_reschedule_uses_tool_result_and_preserves_other_events(self):
        from datetime import timedelta
        from agent.domain.policies import now

        day = (now().date() + timedelta(days=1)).isoformat()
        plans = iter([
            {'action': 'EXECUTAR', 'tool': 'agenda_buscar', 'args': {'termo': 'palestra'}},
            {'action': 'EXECUTAR', 'tool': 'agenda_reagendar', 'args': {'id': 1, 'hora': '10:00', 'revisao': 0}},
            {'action': 'CONFIRMAR', 'context_action': 'RESUME_TASK', 'tool': 'agenda_reagendar',
             'args': {'id': 1, 'hora': '10:00', 'revisao': 0}},
        ])

        def model(messages, schema):
            plan = next(plans)
            if plan['action'] == 'EXECUTAR' and plan.get('tool') == 'agenda_reagendar':
                result = messages[-1]
                self.assertEqual(result['role'], 'tool')
                self.assertEqual(result['tool_name'], 'agenda_buscar')
                self.assertEqual([row['id'] for row in json.loads(result['content'])], [1])
            return json.dumps(plan)

        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', model)
            with app.uow.transaction() as db:
                calendar = app.repository(db).calendar
                calendar.create_event('Palestra', f'{day} 09:00', f'{day} 09:50', 'pessoal', 'normal')
                calendar.create_event('Leitura', f'{day} 14:00', f'{day} 14:20', 'pessoal', 'normal')
            app.handle('owner', 'Mude a palestra para as dez.')
            app.handle('owner', 'Isso mesmo.')
            with app.uow.connection() as db:
                self.assertEqual([tuple(row) for row in db.execute('SELECT title,start,end FROM calendar_events ORDER BY id')],
                                 [('Palestra', f'{day} 10:00', f'{day} 10:50'),
                                  ('Leitura', f'{day} 14:00', f'{day} 14:20')])

    def test_model_cannot_change_preview_at_confirmation(self):
        plans = iter([
            {'action': 'EXECUTAR', 'tool': 'criar_tarefa', 'args': {'texto': 'Tarefa correta'}},
            {'action': 'CONFIRMAR', 'tool': 'criar_tarefa', 'args': {'texto': 'Tarefa diferente'}},
            {'action': 'CONFIRMAR', 'tool': 'criar_tarefa', 'args': {'texto': 'Tarefa diferente'}},
        ])
        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', lambda *_: json.dumps(next(plans)))
            app.handle('owner', 'Crie a tarefa Tarefa correta.')
            app.handle('owner', 'Confirme, mas com o texto Tarefa diferente.')
            with app.uow.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
                memory = app.working_memory_repository(db).load('owner', 'pessoal')
                self.assertEqual(memory.slots['active']['preview']['args'], {'texto': 'Tarefa correta'})

    def test_premature_execution_preserves_validated_fields_and_replans(self):
        plans = iter([
            {'action': 'EXECUTAR', 'context_action': 'CREATE_TASK', 'tool': 'agenda_criar',
             'args': {'titulo': 'Revisão', 'dia_offset': 1, 'hora': '09:00'}},
            {'action': 'PERGUNTAR', 'message': 'Quanto tempo a revisão deve durar?'},
            {'action': 'EXECUTAR', 'context_action': 'COMPLETE_TASK', 'tool': 'agenda_criar',
             'args': {'minutos': 50}},
            {'action': 'CONFIRMAR'},
        ])
        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', lambda *_: json.dumps(next(plans)))
            app.handle('owner', 'Marque uma revisão amanhã às 9.')
            app.handle('owner', 'Cinquenta minutos.')
            with app.uow.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM calendar_events').fetchone()[0], 0)
            app.handle('owner', 'Pode confirmar.')
            with app.uow.connection() as db:
                title, start, end = db.execute('SELECT title,start,end FROM calendar_events').fetchone()
                self.assertEqual((title, start[-5:], end[-5:]), ('Revisão', '09:00', '09:50'))

    def test_ambiguous_reschedule_uses_candidates_persisted_in_previous_turn(self):
        from datetime import timedelta
        from agent.domain.policies import now

        day = (now().date() + timedelta(days=1)).isoformat()
        plans = iter([
            {'action': 'EXECUTAR', 'tool': 'agenda_buscar', 'args': {'termo': 'palestra'}},
            {'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK', 'tool': 'agenda_reagendar',
             'args': {'hora': '10:00'}, 'message': 'Qual das duas palestras?'},
            {'action': 'EXECUTAR', 'context_action': 'UPDATE_TASK', 'tool': 'agenda_reagendar',
             'args': {'id': 2, 'revisao': 0}},
            {'action': 'CONFIRMAR'},
        ])
        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', lambda *_: json.dumps(next(plans)))
            with app.uow.transaction() as db:
                calendar = app.repository(db).calendar
                calendar.create_event('Palestra A', f'{day} 08:00', f'{day} 08:30', 'pessoal', 'normal')
                calendar.create_event('Palestra B', f'{day} 09:00', f'{day} 09:50', 'pessoal', 'normal')
            app.handle('owner', 'Mude a palestra para as dez.')
            app.handle('owner', 'A palestra B.')
            app.handle('owner', 'Isso mesmo.')
            with app.uow.connection() as db:
                starts = [row[0][-5:] for row in db.execute('SELECT start FROM calendar_events ORDER BY id')]
                self.assertEqual(starts, ['08:00', '10:00'])

    def test_complete_execution_plan_only_confirms_an_identical_preview(self):
        raw = iter([
            {'action': 'EXECUTAR', 'context_action': 'CREATE_TASK', 'tool': 'criar_tarefa',
             'args': {'texto': 'Tarefa inicial'}},
            {'action': 'EXECUTAR', 'context_action': 'COMPLETE_TASK', 'tool': 'criar_tarefa',
             'args': {'texto': 'Tarefa corrigida'}},
            {'action': 'EXECUTAR', 'context_action': 'COMPLETE_TASK', 'tool': 'criar_tarefa',
             'args': {'texto': 'Tarefa corrigida'}},
        ])
        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', lambda *_: json.dumps(next(raw)))
            app.handle('owner', 'Crie a tarefa inicial.')
            app.handle('owner', 'Corrija para Tarefa corrigida.')
            with app.uow.connection() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
            app.handle('owner', 'Pode confirmar.')
            with app.uow.connection() as db:
                self.assertEqual(db.execute('SELECT text FROM tasks').fetchone()[0], 'Tarefa corrigida')

    def test_resume_without_id_only_resolves_a_single_suspended_task(self):
        from agent.application.conversation import parse_turn
        from agent.application.planning import PlanError

        raw = '{"action":"RESPONDER","context_action":"RESUME_TASK","message":"Vamos retomar."}'
        self.assertEqual(parse_turn(raw, {}, suspended_ids=[3])['task_id'], 3)
        with self.assertRaises(PlanError):
            parse_turn(raw, {}, suspended_ids=[3, 4])


    def test_reschedule_resolves_model_selected_title_and_checks_revision(self):
        from agent.domain.policies import now
        from datetime import timedelta

        day = (now().date() + timedelta(days=1)).isoformat()
        plans = iter([
            {'action': 'EXECUTAR', 'tool': 'agenda_reagendar',
             'args': {'termo': 'palestra', 'hora': '10:00'}},
            {'action': 'CONFIRMAR'},
        ])
        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', lambda *_: json.dumps(next(plans)))
            with app.uow.transaction() as db:
                calendar = app.repository(db).calendar
                calendar.create_event('Palestra', f'{day} 09:00', f'{day} 09:50', 'pessoal', 'normal')
            app.handle('owner', 'Mude a palestra para as dez.')
            with app.uow.transaction() as db:
                app.repository(db).calendar.update_event(1, f'{day} 11:00', f'{day} 11:50')
            app.handle('owner', 'Isso mesmo.')
            with app.uow.connection() as db:
                start, end, revision = db.execute('SELECT start,end,revision FROM calendar_events').fetchone()
                self.assertEqual((start, end, revision), (f'{day} 11:00', f'{day} 11:50', 1))

    def test_completed_read_does_not_replace_an_incomplete_draft(self):
        plans = iter([
            {'action': 'PERGUNTAR', 'context_action': 'CREATE_TASK', 'tool': 'agenda_criar',
             'args': {'titulo': 'Palestra'}, 'message': 'Qual é a data?'},
            {'action': 'EXECUTAR', 'context_action': 'CREATE_TASK', 'tool': 'financeiro_despesas_dia',
             'args': {'dia_offset': -1}},
            {'action': 'RESPONDER', 'message': 'Aqui está o resultado.'},
        ])
        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', lambda *_: json.dumps(next(plans)))
            app.handle('owner', 'Agende uma palestra.')
            app.handle('owner', 'Quanto gastei ontem?')
            with app.uow.connection() as db:
                state = app.working_memory_repository(db).load('owner', 'pessoal').slots
            self.assertEqual(state['active']['fields'], {'titulo': 'Palestra'})
            self.assertEqual(state['suspended'], [])
