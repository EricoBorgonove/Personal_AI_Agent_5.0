from dataclasses import dataclass
from typing import Protocol
class AgentStrategy(Protocol):
    role: str
    presentation: str
    identity_message: str
    def permits(self, private: bool) -> bool: ...
    def format(self, text: str) -> str: ...
@dataclass(frozen=True)
class PersonalAgent:
    role: str = 'pessoal'
    presentation = (
        '🔐 Olá, professor! Reconheci você como meu proprietário. Sou seu assistente pessoal.\n\n'
        'Posso ajudá-lo com:\n\n'
        '📅 Agenda e compromissos\n'
        '💰 Gestão financeira\n'
        '📋 Tarefas e pendências\n'
        '👥 Solicitações de reuniões\n'
        '🧠 Memória pessoal\n'
        '📚 Documentos privados'
    )
    identity_message = '🔐 Identidade: proprietário\nAgente: PersonalAgent\nPermissão: acesso privado'
    def permits(self,private): return True
    def format(self,text): return text
@dataclass(frozen=True)
class SocialAgent:
    role: str = 'social'
    presentation = (
        '👋 Olá! Sou o assistente virtual do professor Érico Borgonove.\n\n'
        'Posso ajudá-lo com informações, recados e solicitações de reuniões.'
    )
    identity_message = '👥 Identidade: contato externo\nAgente: SocialAgent\nPermissão: acesso restrito'
    def permits(self,private): return not private
    def format(self,text): return 'Assistente virtual: '+text
class AgentFactory:
    def __init__(self,owner): self.owner=owner
    def select(self,sender): return PersonalAgent() if sender==self.owner else SocialAgent()
