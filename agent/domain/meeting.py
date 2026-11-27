from enum import Enum
class State(str, Enum):
    PENDING = 'PENDENTE'
    PROPOSED = 'CONTRAPROPOSTA'
    ACCEPTED = 'ACEITA'
    CONFIRMED = 'CONFIRMADA'
    REJECTED = 'RECUSADA'

def transition(state, action, owner):
    if owner and action == 'confirmo' and state in (State.PENDING, State.ACCEPTED): return State.CONFIRMED
    if owner and action == 'recuso' and state in (State.PENDING, State.ACCEPTED, State.PROPOSED): return State.REJECTED
    if owner and action == 'proponho' and state in (State.PENDING, State.ACCEPTED, State.PROPOSED): return State.PROPOSED
    if not owner and action == 'aceito' and state == State.PROPOSED: return State.ACCEPTED
    return None
