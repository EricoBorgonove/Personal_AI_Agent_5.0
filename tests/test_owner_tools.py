import tempfile
import unittest
from pathlib import Path

from agent.application.agents import PersonalAgent, SocialAgent
from agent.application.conversation import ContextBuilder
from agent.application.executor import Executor
from agent.application.tools import build_registry
from agent.bootstrap import build_app
from agent.domain.policies import now


class OwnerToolsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = build_app(Path(self.directory.name) / 'agent.db', 'owner', lambda *_: '{}')

    def tearDown(self):
        self.directory.cleanup()

    def test_owner_does_not_receive_contact_tools(self):
        with self.app.uow.connection() as db:
            registry = build_registry(self.app.repository(db), 'owner', self.app.knowledge)
            owner, social = registry.available(PersonalAgent()), registry.available(SocialAgent())
            self.assertNotIn('solicitar_reuniao', owner)
            self.assertNotIn('registrar_recado', owner)
            self.assertIn('agenda_criar', owner)
            self.assertIn('solicitar_reuniao', social)
            with self.assertRaises(ValueError):
                Executor(registry, self.app.factory).execute(
                    'owner', 'solicitar_reuniao', {'nome': 'x', 'assunto': 'y', 'horario': '2099-01-01 10:00'})

    def test_owner_prompt_has_no_contact_meeting_defaults(self):
        defaults = {'nome': 'Solicitante', 'duracao': 60}
        state = {'active': None, 'suspended': []}
        owner = ContextBuilder().build(PersonalAgent(), {}, [], 'oi', now(), state, defaults)[0]['content']
        social = ContextBuilder().build(SocialAgent(), {}, [], 'oi', now(), state, defaults)[0]['content']
        self.assertNotIn('Solicitante', owner)
        self.assertIn('agenda_criar', owner)
        self.assertIn('Solicitante', social)


if __name__ == '__main__':
    unittest.main()
