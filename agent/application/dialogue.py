"""Apply model-proposed transitions to structured conversation state."""
import logging
from datetime import timedelta

from .conversation import normalize_times, validate_fields
from .grounding import CHECKED_TOOLS, ungrounded_fields
from .planning import PlanError

logger = logging.getLogger(__name__)


class DialogueManager:
    def apply(self, memory, plan, current, evidence=None):
        tool = plan.get('tool')
        fields = dict(plan['args'])
        transition = plan['context_action']
        if transition == 'COMPLETE_TASK' and plan['action'] == 'EXECUTAR':
            if not memory.active or memory.active['tool'] != tool:
                raise PlanError('tarefa_incompativel')
            # A request to finish the active task can produce a preview, but cannot close it.
            transition = plan['context_action'] = 'UPDATE_TASK'
        if 'dia_offset' in fields:
            offset = fields.pop('dia_offset')
            if not -3660 <= offset <= 3660 or 'data' in fields:
                raise PlanError('data')
            fields['data'] = (current.date() + timedelta(days=offset)).isoformat()
        derived = set()
        if 'inicio_offset_minutos' in fields:
            offset = fields.pop('inicio_offset_minutos')
            if not 1 <= offset <= 1440 or fields.keys() & {'inicio', 'data', 'hora'}:
                raise PlanError('horario')
            if evidence is not None and tool in CHECKED_TOOLS and not evidence.has_minutes(offset):
                raise PlanError('campo_sem_origem_na_conversa:inicio_offset_minutos')
            # The start comes from the clock; the offset itself was checked above.
            derived = {'data', 'hora'}
            start = current + timedelta(minutes=offset)
            fields['data'], fields['hora'] = start.date().isoformat(), start.strftime('%H:%M')
        if tool:
            normalize_times(fields)
            validate_fields(tool, fields)
            if evidence is not None:
                self.require_origin(memory, tool, fields, derived, evidence)
        if transition == 'CREATE_TASK':
            memory.create(tool, fields)
        elif transition == 'UPDATE_TASK':
            if not memory.active or memory.active['tool'] != tool:
                raise PlanError('tarefa_incompativel')
            collected = memory.active['fields']
            merged = self.merge_fields(collected, fields, plan.get('clear_fields', []))
            if collected != merged:
                memory.active['fields'] = merged
                memory.active.pop('preview', None)
            fields = merged
        elif transition == 'SUSPEND_TASK':
            memory.suspend()
        elif transition == 'RESUME_TASK':
            memory.resume(plan['task_id'])
        elif transition in ('CANCEL_TASK', 'COMPLETE_TASK'):
            if plan['action'] == 'EXECUTAR':
                raise PlanError('transicao')
            memory.data['active'] = None
        return fields

    @staticmethod
    def require_origin(memory, tool, fields, derived, evidence):
        """Drop proposed values nobody said; the remaining fields of the plan are kept."""
        collected = memory.active['fields'] if memory.active and memory.active['tool'] == tool else {}
        # Values already stored were checked when they were collected.
        proposed = {key: value for key, value in fields.items()
                    if key not in derived and collected.get(key) != value}
        missing = ungrounded_fields(tool, proposed, evidence, {**collected, **fields})
        for key in missing:
            fields.pop(key)
        if missing:
            logger.info('[SLOTS] descartados_sem_origem campos=%s', ','.join(missing))

    @staticmethod
    def merge_fields(collected, changes, cleared):
        fields = dict(collected)
        if {'data', 'hora'} & set(cleared):
            for key in ('inicio', 'horario'):
                if key in fields:
                    date, hour = fields.pop(key).split(' ', maxsplit=1)
                    fields.update(data=date, hora=hour)
        for key in cleared:
            fields.pop(key, None)
        alternatives = (
            ('inicio', {'data', 'hora'}),
            ('horario', {'data', 'hora'}),
            ('minutos', {'fim', 'fim_hora'}),
            ('fim', {'fim_hora'}),
        )
        for key, others in alternatives:
            if key in changes:
                for other in others:
                    fields.pop(other, None)
            elif changes.keys() & others:
                previous = fields.pop(key, None)
                if previous and key in ('inicio', 'horario'):
                    date, hour = previous.split(' ', maxsplit=1)
                    fields.update(data=date, hora=hour)
        fields.update(changes)
        return fields
