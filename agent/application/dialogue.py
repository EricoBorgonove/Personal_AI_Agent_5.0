"""Apply model-proposed transitions to structured conversation state."""
from datetime import timedelta

from .conversation import normalize_times, validate_fields
from .planning import PlanError


class DialogueManager:
    def apply(self, memory, plan, current):
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
        if 'inicio_offset_minutos' in fields:
            offset = fields.pop('inicio_offset_minutos')
            if not 1 <= offset <= 1440 or fields.keys() & {'inicio', 'data', 'hora'}:
                raise PlanError('horario')
            start = current + timedelta(minutes=offset)
            fields['data'], fields['hora'] = start.date().isoformat(), start.strftime('%H:%M')
        if tool:
            normalize_times(fields)
            validate_fields(tool, fields)
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
