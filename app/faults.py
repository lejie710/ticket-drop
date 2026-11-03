"""Seeded faults for measuring test effectiveness.

Each fault is a deliberate, named bug that is switched off unless its name
appears in the TICKET_DROP_FAULTS environment variable. The clean application
never enables one. The catalogue below describes what each fault breaks, so a
result can be traced to the bug that caused it.
"""

CATALOGUE: dict[str, str] = {}


def on(settings, name: str) -> bool:
    if name not in CATALOGUE:
        raise KeyError(f"unknown fault {name!r}")
    return name in settings.faults
