from .application.orchestrator import Orchestrator
from .infrastructure.sqlite import SQLiteUnitOfWork
from .infrastructure.repositories import Repository
from .infrastructure.ollama import ask_ollama
from .infrastructure.rag import LocalKnowledgeBase

def build_app(path,owner,model=ask_ollama,knowledge=None):
    return Orchestrator(SQLiteUnitOfWork(path),Repository,owner,model,knowledge or LocalKnowledgeBase())
