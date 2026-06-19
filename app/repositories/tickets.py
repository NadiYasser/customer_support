"""Ticket repository — mocked, swappable interface.

In-memory ticket store for the IT support agent. The interface is deliberately
minimal so a real Jira/Zendesk/Linear client can implement the same shape later.
"""


class TicketRepository:
    def __init__(self):
        self._tickets: list[dict] = []

    def create_ticket(self, subject: str, description: str, severity: str = "normal") -> dict:
        ticket = {
            "id": len(self._tickets) + 1,
            "subject": subject,
            "description": description,
            "severity": severity,
            "status": "open",
        }
        self._tickets.append(ticket)
        return ticket
