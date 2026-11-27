import unittest
from agent.domain.meeting import State, transition
from agent.application.agents import AgentFactory
from agent.application.tools import ToolRegistry, ToolCommand
from agent.application.executor import Executor

class PatternTests(unittest.TestCase):
    def test_factory_and_permissions(self):
        factory=AgentFactory('owner'); registry=ToolRegistry()
        registry.register(ToolCommand('private','{}',True,lambda s,a:'secret'))
        registry.register(ToolCommand('public','{}',False,lambda s,a:'ok'))
        self.assertEqual(set(registry.available(factory.select('guest'))),{'public'})
        executor=Executor(registry,factory)
        with self.assertRaises(ValueError): executor.execute('guest','private',{})
        self.assertEqual(executor.execute('owner','private',{}),'secret')
        self.assertEqual(executor.execute('guest','public',{}),'ok')
        with self.assertRaises(ValueError): executor.execute('guest','missing',{})
        with self.assertRaises(ValueError): registry.register(ToolCommand('public','{}',False,lambda s,a:None))
    def test_state_machine(self):
        self.assertIsNone(transition(State.PENDING,'confirmo',False))
        self.assertIsNone(transition(State.PROPOSED,'confirmo',True))
        self.assertEqual(transition(State.PENDING,'proponho',True),State.PROPOSED)
        self.assertEqual(transition(State.PROPOSED,'aceito',False),State.ACCEPTED)
        self.assertEqual(transition(State.ACCEPTED,'confirmo',True),State.CONFIRMED)
        self.assertIsNone(transition(State.CONFIRMED,'recuso',True))
