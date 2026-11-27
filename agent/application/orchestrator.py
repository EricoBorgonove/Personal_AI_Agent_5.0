import copy
import json
import logging
import re
from threading import Lock
from time import monotonic
from uuid import uuid4

from agent.diagnostics import safe_traceback
from agent.domain.policies import now

from .agents import AgentFactory
from .calendar_reminders import CalendarReminderService
from .conversation import (ContextBuilder, READ_TOOLS, is_affirmation, parse_turn, required_fields,
                           resolve_args, turn_schema)
from .dialogue import DialogueManager
from .executor import Executor
from .grounding import Evidence
from .meetings import MeetingService
from .planning import PlanError
from .reminders import FinanceReminderService
from .responses import ResponseBuilder
from .specialists.calendar import CalendarService
from .specialists.finance import FinanceService
from .specialists.obligations import ObligationsService
from .tools import build_registry
from .working_memory import COMMANDS, WorkingMemoryManager

logger = logging.getLogger(__name__)
MAX_TOOLS = 5


class Orchestrator:
    def __init__(self,uow,repository,owner,model,knowledge,*,working_memory_repository,meeting_duration=60):
        self.uow,self.repository,self.owner,self.model,self.knowledge=uow,repository,owner,model,knowledge
        self.factory=AgentFactory(owner)
        self.context = ContextBuilder()
        self.dialogue = DialogueManager()
        self.meeting_duration = meeting_duration
        self.responses=ResponseBuilder()
        self.working_memory_repository = working_memory_repository
        self._outbox_lock = Lock()
    def handle(self, sender, text, event_id=None, *, reply_to=None, presentation_keys=(), display_name=None):
        request_id = uuid4().hex[:12]
        agent = self.factory.select(sender)
        recipient = reply_to or sender
        logger.info('[IDENTITY] req=%s perfil=%s', request_id, agent.role)
        command = text.strip().casefold()
        with self.uow.transaction() as db:
            repo = self.repository(db)
            if event_id and repo.event_seen(sender, event_id):
                logger.info('mensagem_duplicada req=%s', request_id)
                return
            if command == '/identidade':
                answer = agent.identity_message
            elif command in COMMANDS:
                memory = self._memory(db, sender, agent.role)
                answer = self._memory_command(repo, memory, sender, command)
            else:
                answer = self._administrative(repo, sender, agent.permits(True), text, request_id)
            if answer is not None:
                if event_id:
                    repo.seen(sender, event_id)
                self._deliver(repo, sender, recipient, agent, presentation_keys, text, answer,
                              'deterministica', request_id, record=command not in {*COMMANDS, '/identidade'},
                              format_reply=command != '/identidade')
                return

        for attempt in range(2):
            with self.uow.connection() as db:
                repo = self.repository(db)
                if event_id and repo.event_seen(sender, event_id):
                    return
                revision = repo.conversation_revision(sender)
                memory = self._memory(db, sender, agent.role)
                stored = memory.loaded
                legacy = repo.dialogue(sender)
                history = repo.history(sender)
                registry = build_registry(repo, self.owner, self.knowledge)
                executor = Executor(registry, self.factory)
                answer, source, confirmation = self._conversation(
                    executor, memory, agent, text, request_id, display_name, history, legacy,
                )
            with self.uow.transaction() as db:
                repo = self.repository(db)
                if event_id and repo.event_seen(sender, event_id):
                    return
                current = self._memory(db, sender, agent.role)
                if (repo.conversation_revision(sender), current.loaded, repo.dialogue(sender)) != (revision, stored, legacy):
                    logger.info('[CONTEXT] concorrente req=%s tentativa=%d', request_id, attempt + 1)
                    continue
                if event_id:
                    repo.seen(sender, event_id)
                memory.repository = current.repository
                if confirmation:
                    answer = self._confirm(repo, memory, sender, confirmation, request_id)
                elif memory.data != current.data:
                    memory.save()
                    logger.info('[MEMORY] atualizado req=%s ativa=%s', request_id, bool(memory.active))
                if legacy:
                    repo.clear_dialogue(sender)
                self._deliver(repo, sender, recipient, agent, presentation_keys, text, answer, source, request_id)
                return

        with self.uow.transaction() as db:
            repo = self.repository(db)
            if not event_id or not repo.seen(sender, event_id):
                self._deliver(repo, sender, recipient, agent, presentation_keys, text,
                              'Recebi outra mensagem enquanto preparava a resposta. Pode repetir o pedido?',
                              'deterministica', request_id)

    def _memory(self, db, sender, role):
        return WorkingMemoryManager(self.working_memory_repository(db), sender, role)

    @staticmethod
    def _deliver(repo, sender, recipient, agent, presentation_keys, text, answer, source, request_id, *,
                 record=True, format_reply=True):
        if presentation_keys and repo.mark_presentation(presentation_keys, agent.role):
            repo.notify(recipient, agent.presentation)
        answer = answer[:3500]
        if format_reply:
            answer = agent.format(answer)
        logger.info('[RESPONSE] req=%s origem=%s', request_id, source)
        if record:
            repo.record(sender, text, answer)
        repo.notify(recipient, answer)

    def _administrative(self, repo, sender, owner, text, request_id):
        try: answer=MeetingService(repo,self.owner).decision(sender,text)
        except ValueError as ex:
            logger.warning('decisao_rejeitada req=%s tipo=reuniao\n%s', request_id, safe_traceback(ex))
            answer=str(ex)
        if owner and (m := re.fullmatch(r"Estorno o lançamento #(\d+)",text.strip(),re.IGNORECASE)):
            answer="Lançamento estornado." if FinanceService(repo.finance).void(int(m.group(1))) else "Lançamento inexistente ou já estornado."
        if owner and (m := re.fullmatch(r"(Liquido|Cancelo) a conta #(\d+)(?: em (\d{4}-\d{2}-\d{2}))?",text.strip(),re.IGNORECASE)):
            try:
                with repo.atomic():
                    service=ObligationsService(repo.obligations,repo.finance)
                    if m.group(1).lower()=='liquido': answer='Conta liquidada: '+json.dumps(service.settle(int(m.group(2)),m.group(3) or now().date().isoformat()),ensure_ascii=False)
                    else: service.cancel(int(m.group(2))); answer='Conta cancelada.'
            except ValueError as ex:
                logger.warning('decisao_rejeitada req=%s tipo=conta\n%s', request_id, safe_traceback(ex))
                answer=str(ex)
        if owner and (m := re.fullmatch(r"Cancelo o compromisso #(\d+)",text.strip(),re.IGNORECASE)):
            try:
                with repo.atomic(): CalendarService(repo.calendar).cancel(int(m[1]))
                answer='Compromisso cancelado.'
            except ValueError as ex:
                logger.warning('decisao_rejeitada req=%s tipo=cancelamento\n%s', request_id, safe_traceback(ex))
                answer=str(ex)
        if owner and (m := re.fullmatch(r"Reagendo o compromisso #(\d+) para (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) até (\d{4}-\d{2}-\d{2} \d{2}:\d{2})",text.strip(),re.IGNORECASE)):
            try:
                with repo.atomic(): CalendarService(repo.calendar).change(int(m[1]),m[2],m[3])
                answer='Compromisso reagendado.'
            except ValueError as ex:
                logger.warning('decisao_rejeitada req=%s tipo=reagendamento\n%s', request_id, safe_traceback(ex))
                answer=str(ex)
        return answer

    def _confirm(self, repo, memory, sender, preview, request_id):
        executor = Executor(build_registry(repo, self.owner, self.knowledge), self.factory)
        try:
            with repo.atomic():
                result = self._verified_execution(executor, sender, preview['tool'], preview['args'], request_id)
                memory.complete_active()
                if memory.data['suspended']:
                    memory.save()
                else:
                    memory.repository.clear(sender, memory.role)
        except Exception as error:
            logger.error('[RESULT] etapa_revertida req=%s\n%s', request_id, safe_traceback(error))
            return 'A operação falhou. O rascunho continua disponível em /contexto.'
        logger.info('[MEMORY] atualizado req=%s ativa=false', request_id)
        return self.responses.results([(preview['tool'], result, preview['args'])])

    @staticmethod
    def _memory_command(repo, memory, sender, command):
        if command == '/contexto':
            if legacy := repo.dialogue(sender):
                memory.add_suspended('solicitar_reuniao' if legacy.get('kind') == 'meeting' else 'registrar_recado',
                                     {key: value for key, value in legacy.items() if key != 'kind'})
            return ResponseBuilder.task_context(memory.active, memory.data['suspended'])
        memory.repository.clear(sender, memory.role)
        repo.clear_dialogue(sender)
        if command == '/novaconversa':
            repo.reset_conversation(sender)
            return 'Nova conversa iniciada.'
        return 'Rascunhos da conversa cancelados.'

    def _conversation(self, executor, memory, agent, text, request_id, display_name, history, legacy):
        tools = executor.registry.available(agent)
        state = memory.data
        current = now()
        if legacy:
            tool = 'solicitar_reuniao' if legacy.get('kind') == 'meeting' else 'registrar_recado'
            memory.add_suspended(tool, {key: value for key, value in legacy.items()
                                       if key != 'kind' and value is not None})
        preview = (memory.active or {}).get('preview')
        if preview and preview['tool'] in tools and is_affirmation(text):
            # A literal approval needs no interpretation; the Executor still checks permissions.
            logger.info('[PLAN] confirmacao_deterministica req=%s ferramenta=%s', request_id, preview['tool'])
            return '', 'deterministica', preview
        defaults ={'nome': (display_name or 'Solicitante')[:150], 'duracao': self.meeting_duration}
        task_context = copy.deepcopy(state)
        task_context.pop('next_id')
        for task in [task_context['active'], *task_context['suspended']]:
            if task and task['tool'] in tools:
                task['missing'] = required_fields(task['tool'], tools, task['fields'])
        logger.info('[CONTEXT] req=%s mensagens=%d ferramentas=%d', request_id, len(history), len(tools))
        logger.info('[MEMORY] req=%s ativa=%s suspensas=%d', request_id,
                    bool(memory.active), len(state['suspended']))
        messages = self.context.build(agent, tools, history, text, current, task_context, defaults)
        results = []
        used = set()
        retried = False
        previous = next((item['content'] for item in reversed(history) if item['role'] == 'assistant'), '')
        for step in range(MAX_TOOLS + 2):
            before = copy.deepcopy(memory.data)
            started = monotonic()
            try:
                logger.info('[LLM] envio req=%s etapa=%d', request_id, step)
                plan = parse_turn(
                    self.model(messages, turn_schema(tools)), tools,
                    active_tool=(memory.active or {}).get('tool'),
                    preview_tool=((memory.active or {}).get('preview') or {}).get('tool'),
                    suspended_ids=[task['id'] for task in memory.data['suspended'] if task['tool'] in tools],
                )
                action, transition, tool = plan['action'], plan['context_action'], plan.get('tool')
                logger.info('[LLM] validado req=%s duracao_ms=%d', request_id, (monotonic()-started)*1000)
                logger.info('[INTENT] req=%s acao=%s ferramenta=%s', request_id, action, tool)
                logger.info('[SLOTS] req=%s campos=%s', request_id, sorted(plan['args']))
                logger.info('[PLAN] req=%s acao=%s transicao=%s', request_id, action, transition)
                if action == 'NEGAR':
                    return 'Esse pedido exige acesso autorizado.', 'deterministica', None
                if action == 'CONFIRMAR':
                    preview = (memory.active or {}).get('preview')
                    if not preview or results:
                        raise PlanError('sem_previa')
                    if tool and (tool != preview['tool'] or
                                 any(preview['args'].get(key) != value for key, value in plan['args'].items())):
                        raise PlanError('confirmacao_altera_previa')
                    return '', 'deterministica', preview
                completes_active = action == 'EXECUTAR' and transition == 'COMPLETE_TASK'
                fields = self.dialogue.apply(memory, plan, current,
                                             self._evidence(text, history, memory, results, current))
                transition = plan['context_action']
                if tool == 'solicitar_reuniao' and action == 'EXECUTAR':
                    fields = {**defaults, **fields}

                prior_task = before['active'] or {}
                prior_candidates = []
                if transition == 'UPDATE_TASK' and fields.get('termo') == prior_task.get('fields', {}).get('termo'):
                    prior_candidates = prior_task.get('candidates', [])
                found_events = [row for name, rows, _ in results if name == 'agenda_buscar' for row in rows]
                if tool == 'agenda_reagendar' and fields.get('termo') and not (prior_candidates or found_events):
                    search = {'termo': fields['termo']}
                    search_key = json.dumps(['agenda_buscar', search], sort_keys=True, ensure_ascii=False)
                    if search_key not in used:
                        found_events = self._verified_execution(executor, memory.sender, 'agenda_buscar', search, request_id)
                        results.append(('agenda_buscar', found_events, search))
                        used.add(search_key)
                        self.context.add_tool_result(messages, plan, 'agenda_buscar', found_events)
                        if action == 'PERGUNTAR':
                            if memory.active and memory.active['tool'] == tool:
                                memory.active['candidates'] = found_events
                            continue
                if action != 'EXECUTAR':
                    message = self.responses.model_message(
                        plan, self._evidence(text, history, memory, results, current))
                    if action == 'PERGUNTAR' and tool == 'agenda_reagendar' and found_events:
                        if memory.active and memory.active['tool'] == tool:
                            memory.active['candidates'] = found_events
                    prior_fields = (before['active'] or {}).get('fields')
                    current_fields = (memory.active or {}).get('fields')
                    if (action == 'PERGUNTAR' and prior_fields == current_fields
                            and self._same_question(agent.format(message), previous)):
                        raise PlanError('pergunta_sem_progresso')
                    if results:
                        answer = self.responses.results(results)
                        return (answer + '\n\n' + message, 'mista', None) if action == 'PERGUNTAR' else (answer, 'deterministica', None)
                    return message, 'llm', None

                missing = required_fields(tool, tools, fields)
                if missing:
                    if transition in ('CREATE_TASK', 'UPDATE_TASK'):
                        # Keep validated fields when the planner attempts execution too early.
                        before = copy.deepcopy(memory.data)
                        messages[0]['content'] += (
                            '\nCampos validados durante este turno: ' + json.dumps(fields, ensure_ascii=False)
                        )
                    raise PlanError('campos_ausentes:' + ','.join(missing))
                args = resolve_args(tool, fields, current)
                details = None
                if tool == 'agenda_reagendar':
                    candidates = found_events or prior_candidates
                    if len(found_events) > 1:
                        raise PlanError('mais_de_um_compromisso_qual_deles')
                    if 'termo' in args:
                        args.pop('termo')
                        if 'id' not in args and len(candidates) == 1:
                            args.update(id=candidates[0]['id'], revisao=candidates[0]['revision'])
                    matches = [row for row in candidates
                               if (row['id'], row['revision']) == (args.get('id'), args.get('revisao'))]
                    if len(matches) != 1:
                        raise PlanError('consulte_o_compromisso_antes_de_reagendar')
                    event = matches[0]
                    details = {'compromisso': event['title'], 'início atual': event['start'],
                               'novo início': event['start'].split(' ')[0] + ' ' + args['hora']}
                prior_preview = prior_task.get('preview')
                if completes_active and not results and prior_preview:
                    if (tool, args) == (prior_preview['tool'], prior_preview['args']):
                        return '', 'deterministica', prior_preview
                key = json.dumps([tool, args], sort_keys=True, ensure_ascii=False)
                if key in used:
                    raise PlanError('chamada_repetida')
                if tool not in READ_TOOLS:
                    if transition not in ('CREATE_TASK', 'UPDATE_TASK'):
                        if memory.active and memory.active['tool'] == tool:
                            raise PlanError('use_UPDATE_TASK_para_usar_o_rascunho')
                        memory.create(tool, fields)
                    memory.active['preview'] = {'tool': tool, 'args': args}
                    if details:
                        memory.active['preview']['details'] = details
                        memory.active['candidates'] = matches
                    answer = self.responses.preview(tool, args, details)
                    additional_results = [entry for entry in results if not details or entry[0] != 'agenda_buscar']
                    if additional_results:
                        answer = self.responses.results(additional_results) + '\n\n' + answer
                    return answer, 'deterministica', None
                result = self._verified_execution(executor, memory.sender, tool, args, request_id)
                if transition in ('CREATE_TASK', 'UPDATE_TASK'):
                    memory.complete_read(before['active'] if transition == 'CREATE_TASK' else None)
                used.add(key)
                results.append((tool, result, args))
                if len(used) == MAX_TOOLS:
                    return self.responses.results(results), 'deterministica', None
                self.context.add_tool_result(messages, plan, tool, result)
            except Exception as error:
                memory.data = before
                reason = error.args[0] if isinstance(error, PlanError) else type(error).__name__
                logger.error('[PLAN] rejeitado req=%s motivo=%s duracao_ms=%d',
                             request_id, reason, (monotonic() - started) * 1000)
                if retried:
                    break
                retried = True
                messages[0]['content'] += (
                    f'\nReavalie a última mensagem e os campos já coletados. Motivo: {reason}. '
                    'Se faltarem campos para EXECUTAR, mude action para PERGUNTAR, '
                    'inclua message com a pergunta sobre esses campos e preserve em args apenas os dados novos.'
                )
        if results:
            return self.responses.results(results, incomplete=True), 'deterministica', None
        if (memory.active or {}).get('preview'):
            return 'O rascunho continua disponível em /contexto. Confirme ou indique o campo que deseja corrigir.', 'deterministica', None
        active = memory.active
        if active and active['tool'] in tools:
            missing = required_fields(active['tool'], tools, active['fields'])
            if missing:
                answer = self.responses.missing_details(missing)
                return answer, 'deterministica', None
        return self.responses.failure(), 'deterministica', None

    @staticmethod
    def _evidence(text, history, memory, results, current):
        speech = '\n'.join([text, *(item['content'] for item in history if item['role'] == 'user')])
        records = '\n'.join([*(item['content'] for item in history if item['role'] != 'user'),
                             json.dumps(memory.data, ensure_ascii=False),
                             json.dumps([row for _, row, _ in results], ensure_ascii=False)])
        return Evidence(speech, records, current.date())

    @staticmethod
    def _same_question(left, right):
        return (' '.join(left.casefold().strip(' ?.!').split()) ==
                ' '.join(right.casefold().strip(' ?.!').split()))

    @staticmethod
    def _verified_execution(executor, sender, tool, args, request_id):
        result = executor.execute(sender, tool, args, request_id=request_id)
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        logger.info('[RESULT] req=%s ferramenta=%s status=concluida', request_id, tool)
        return result

    def enqueue_finance_reminders(self):
        with self.uow.transaction() as d:
            return FinanceReminderService(self.repository(d),self.owner).enqueue()
    def enqueue_calendar_reminders(self):
        with self.uow.transaction() as d:
            return CalendarReminderService(self.repository(d),self.owner).enqueue()
    def flush(self, send):
        with self._outbox_lock, self.uow.connection() as db:
            repo = self.repository(db)
            for item in repo.pending():
                try:
                    send(item['recipient'], item['text'])
                except Exception as error:
                    logger.error('envio_pendente\n%s', safe_traceback(error))
                    continue
                with db:
                    repo.delivered(item['id'])
