import re
from dataclasses import dataclass
from typing import Callable

PHONE_SERVER = 's.whatsapp.net'
LID_SERVER = 'lid'
JID_PATTERN = re.compile(
    r'([0-9]+)(?:\.[0-9]+)?(?::[0-9]+)?@(s\.whatsapp\.net|lid)',
    re.IGNORECASE | re.ASCII,
)


def normalize_jid(value: str | None) -> str | None:
    match = JID_PATTERN.fullmatch(value.strip()) if value else None
    if match is not None:
        return f'{match[1]}@{match[2].lower()}'
    return None


def jid_server(jid: str) -> str:
    return jid.split('@', 1)[1]


@dataclass(frozen=True)
class ResolvedIdentity:
    sender: str
    principal: str
    alternate: str | None
    matched_by: str

    @property
    def presentation_keys(self) -> tuple[str, ...]:
        if self.principal == self.sender and self.alternate:
            return (self.principal, self.alternate)
        return (self.principal,)


class IdentityResolver:
    def __init__(self, owner_jid: str, owner_lid: str = ''):
        owner = normalize_jid(owner_jid)
        if owner is None:
            raise ValueError('Configure OWNER_JID com o JID do proprietário.')
        self.owner_jid = owner
        self.owner_lid = normalize_jid(owner_lid)
        if owner_lid.strip() and (
            self.owner_lid is None or jid_server(self.owner_lid) != LID_SERVER
            or (jid_server(owner) == LID_SERVER and owner != self.owner_lid)
        ):
            raise ValueError('Configure OWNER_LID com um @lid verificado e compatível com OWNER_JID.')

    def resolve(
        self,
        sender: str,
        alternate: str | None = None,
        lookup: Callable[[], str | None] | None = None,
    ) -> ResolvedIdentity:
        sender = normalize_jid(sender)
        if sender is None:
            raise ValueError('JID do remetente inválido')
        server = jid_server(sender)
        owner_server = jid_server(self.owner_jid)

        linked = normalize_jid(alternate)
        if linked is not None and jid_server(linked) == server:
            linked = None
        evidence = 'sender_alt'
        if linked is None and lookup is not None and (server == LID_SERVER or owner_server == LID_SERVER):
            linked = normalize_jid(lookup())
            if linked is not None and jid_server(linked) == server:
                linked = None
            evidence = 'neonize_store'

        if sender == self.owner_jid:
            return ResolvedIdentity(sender, sender, linked, 'jid_configurado')
        if linked == self.owner_jid:
            return ResolvedIdentity(sender, self.owner_jid, linked, evidence)
        if owner_server == PHONE_SERVER and sender == self.owner_lid:
            if linked is None:
                return ResolvedIdentity(sender, self.owner_jid, None, 'lid_configurado')
            return ResolvedIdentity(sender, sender, linked, 'telefone_divergente')
        return ResolvedIdentity(sender, sender, linked, 'sem_correspondencia')
