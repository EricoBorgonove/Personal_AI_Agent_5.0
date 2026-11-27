import os

from .application.orchestrator import Orchestrator
from .infrastructure.sqlite import SQLiteUnitOfWork
from .infrastructure.repositories import Repository
from .infrastructure.ollama import ask_ollama
from .infrastructure.rag import LocalKnowledgeBase

def build_app(path,owner,model=ask_ollama,knowledge=None,*,meeting_duration=None):
    if meeting_duration is None:
        meeting_duration = int(os.getenv('MEETING_DURATION_MINUTES','60'))
    if type(meeting_duration) is not int or not 1 <= meeting_duration <= 1440:
        raise ValueError('MEETING_DURATION_MINUTES deve ter entre 1 e 1440 minutos.')
    return Orchestrator(SQLiteUnitOfWork(path),Repository,owner,model,knowledge or LocalKnowledgeBase(),
                        meeting_duration=meeting_duration)
