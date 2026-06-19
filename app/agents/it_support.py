"""IT support agent (M3).

For merchants reporting website trouble. A create_react_agent loop with one tool,
create_ticket, backed by a swappable TicketRepository (mocked now, real
Jira/Zendesk later).
"""
from langchain.agents import create_agent

from app.config import get_model
from app.tools.it_support import create_ticket

SYSTEM_PROMPT = (
    "You are an IT support assistant for an online store's merchants. "
    "When a merchant reports a technical problem with the website — checkout "
    "failures, pages not loading, login issues, etc. — gather a short subject and "
    "a description and use the create_ticket tool to open a ticket. Set severity "
    "to 'high' for anything blocking sales. Confirm the ticket number back to the "
    "merchant. Answer in a friendly, concise way."
)

it_support_agent = create_agent(
    model=get_model(),
    tools=[create_ticket],
    system_prompt=SYSTEM_PROMPT,
)
