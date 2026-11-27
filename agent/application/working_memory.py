"""Persistence and lifecycle for a sender's structured tasks."""
import copy

from agent.domain.working_memory import Draft

COMMANDS = {'/contexto', '/cancelar', '/novaconversa'}


class WorkingMemoryManager:
    """Transactional conversation state, isolated by authenticated sender and role."""

    def __init__(self, repository, sender, role):
        self.repository, self.sender, self.role = repository, sender, role
        stored = repository.load(sender, role)
        self.loaded = stored
        self.data = copy.deepcopy(stored.slots) if stored and stored.tool == 'conversation_v2' else {
            'active': None, 'suspended': [], 'next_id': 1,
        }
        # Older drafts remain available as suspended tasks, requiring an explicit resume.
        if stored and stored.tool != 'conversation_v2':
            fields = {'fim_hora' if key == 'fim' and stored.tool == 'agenda_criar' else key: value
                      for key, value in stored.slots.items()}
            self.add_suspended(stored.tool, fields)

    @property
    def active(self):
        return self.data['active']

    def create(self, tool, fields):
        self.suspend()
        self.data['active'] = {'id': self.data['next_id'], 'tool': tool, 'fields': dict(fields)}
        self.data['next_id'] += 1

    def add_suspended(self, tool, fields):
        task = {'id': self.data['next_id'], 'tool': tool, 'fields': dict(fields)}
        self.data['next_id'] += 1
        self.data['suspended'] = [*self.data['suspended'], task][-5:]

    def suspend(self):
        if self.active:
            self.active.pop('preview', None)
            self.data['suspended'] = [*self.data['suspended'], self.active][-5:]
            self.data['active'] = None

    def resume(self, task_id):
        for index, task in enumerate(self.data['suspended']):
            if task['id'] == task_id:
                self.data['suspended'].pop(index)
                self.suspend()
                self.data['active'] = task
                return
        raise ValueError('Tarefa suspensa inexistente.')

    def complete_active(self):
        """Close the executed task and drop suspended copies of it, so it cannot run twice."""
        done = self.active
        self.data['active'] = None
        if done:
            self.data['suspended'] = [task for task in self.data['suspended']
                                      if (task['tool'], task['fields']) != (done['tool'], done['fields'])]

    def complete_read(self, interrupted):
        self.data['active'] = interrupted
        if interrupted:
            self.data['suspended'] = [task for task in self.data['suspended']
                                      if task['id'] != interrupted['id']]

    def save(self):
        self.repository.save(self.sender, self.role, Draft('conversation_v2', self.data, {}))
