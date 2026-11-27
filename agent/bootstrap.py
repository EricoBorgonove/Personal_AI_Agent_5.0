import os

from .application.orchestrator import Orchestrator
from .infrastructure.sqlite import SQLiteUnitOfWork
from .infrastructure.repositories import Repository
from .infrastructure.ollama import ask_ollama
from .infrastructure.rag import LocalKnowledgeBase
from .infrastructure.working_memory_repository import WorkingMemoryRepository

def build_app(path,owner,model=ask_ollama,knowledge=None,*,meeting_duration=None,turn_budget=None):
    if meeting_duration is None:
        meeting_duration = int(os.getenv('MEETING_DURATION_MINUTES','60'))
    if type(meeting_duration) is not int or not 1 <= meeting_duration <= 1440:
        raise ValueError('MEETING_DURATION_MINUTES deve ter entre 1 e 1440 minutos.')
    if turn_budget is None:
        turn_budget = int(os.getenv('TURN_TIMEOUT_SECONDS', '90'))
    if type(turn_budget) is not int or turn_budget < 0:
        raise ValueError('TURN_TIMEOUT_SECONDS deve ser um inteiro não negativo.')
    return Orchestrator(SQLiteUnitOfWork(path),Repository,owner,model,knowledge or LocalKnowledgeBase(),
                        working_memory_repository=WorkingMemoryRepository, meeting_duration=meeting_duration,
                        turn_budget=turn_budget)
