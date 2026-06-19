"""Tool for the IT support agent (M3).

create_ticket is a thin @tool over TicketRepository. Unlike the order tools,
this writes to a separate ticket store — the interface is deliberately minimal
so a real Jira/Zendesk/Linear client can implement the same shape later.
"""
from langchain_core.tools import tool

from app.repositories.tickets import TicketRepository

_tickets = TicketRepository()


@tool
def create_ticket(subject: str, description: str, severity: str = "normal") -> str:
    """Open an IT support ticket for a website or technical problem.

    Use this when a merchant reports something broken — checkout failing, pages
    not loading, login issues, etc. Summarize the problem in the subject and put
    the details in the description.

    Args:
        subject: Short summary of the problem.
        description: Fuller description of what's going wrong.
        severity: One of "low", "normal", "high". Default "normal".
    """
    ticket = _tickets.create_ticket(subject, description, severity)
    return f"Ticket #{ticket['id']} created ({ticket['severity']} severity): {ticket['subject']}."
