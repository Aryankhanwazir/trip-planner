# ruff: noqa
import os
import re
import json
import logging
from typing import AsyncGenerator
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from mcp import StdioServerParameters
from google.adk.workflow import Workflow, Edge, START, node
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from .config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TripPlannerAgent")

# ── Model & MCP Toolset ────────────────────────────────────────────────────────
model_client = Gemini(model=config.model)

mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="uv",
        args=["run", "app/mcp_server.py"],
    )
)

# ── Sub-agents ─────────────────────────────────────────────────────────────────
destination_agent = LlmAgent(
    name="destination_agent",
    model=model_client,
    instruction="""You are a destination travel expert.
Given a destination, list the top 5 attractions and give 2-3 practical travel tips (weather, transport, safety).
Format your response as:
ATTRACTIONS:
- <attraction 1>
- <attraction 2>
- <attraction 3>
- <attraction 4>
- <attraction 5>
TIPS: <tips text>
Use the get_attraction_reviews and get_safety_index tools for local details.""",
    tools=[mcp_toolset],
)

budget_agent = LlmAgent(
    name="budget_agent",
    model=model_client,
    instruction="""You are a travel budget advisor.
Given a destination, duration, and budget, estimate if the budget is sufficient.
Use get_flight_estimate and get_exchange_rate tools for accurate estimates.
Format your response as:
ESTIMATED_COST: <number in USD>
STATUS: sufficient|insufficient
BREAKDOWN: <brief cost breakdown>
ADVICE: <one practical tip>""",
    tools=[mcp_toolset],
)

# ── Helper: parse trip details from plain text ─────────────────────────────────
def parse_trip_details(text: str) -> dict | None:
    """Extract destination, duration and budget from user message using regex."""
    text_lower = text.lower()

    # Budget: $3000, 3000 USD, 3000 dollars, budget of 3000
    budget_match = re.search(
        r'\$\s*(\d[\d,]*)|(\d[\d,]*)\s*(?:usd|dollars?|budget)',
        text_lower
    )
    budget = float(budget_match.group(1) or budget_match.group(2).replace(',', '')) if budget_match else None

    # Duration: 7 days, 7-day, for 7 days
    duration_match = re.search(r'(\d+)\s*(?:-\s*)?days?', text_lower)
    duration = int(duration_match.group(1)) if duration_match else None

    # Destination: "to X", "in X", "visit X", "trip to X"
    dest_match = re.search(
        r'(?:to|in|visit|for|trip to)\s+([A-Za-z][A-Za-z\s\-]+?)(?:\s+for|\s+with|\s+in|\s+on|\s*,|\s*\.|$)',
        text,
        re.IGNORECASE
    )
    destination = dest_match.group(1).strip().title() if dest_match else None

    if destination and duration and budget:
        return {"destination": destination, "duration_days": duration, "budget_usd": budget}
    return None

# ── Helper: parse agent response fields ───────────────────────────────────────
def extract_field(text: str, field: str, default: str = "") -> str:
    """Pull a labeled field from agent free-text response."""
    m = re.search(rf'{field}:\s*(.+?)(?:\n[A-Z_]+:|$)', text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else default

def extract_attractions(text: str) -> list[str]:
    """Pull bulleted attractions list."""
    section = re.search(r'ATTRACTIONS?:(.*?)(?:TIPS?:|$)', text, re.IGNORECASE | re.DOTALL)
    if not section:
        return ["See local highlights"]
    items = re.findall(r'-\s*(.+)', section.group(1))
    return [i.strip() for i in items if i.strip()] or ["See local highlights"]

# ── Security Checkpoint ────────────────────────────────────────────────────────
@node
def security_checkpoint(ctx: Context, node_input: types.Content) -> Event:
    user_text = ""
    if node_input and node_input.parts:
        user_text = "".join([p.text for p in node_input.parts if p.text])

    # PII scrubbing
    scrubbed = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '[EMAIL_REDACTED]', user_text)
    scrubbed = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE_REDACTED]', scrubbed)

    # Injection detection
    injection_keywords = ["ignore previous instructions", "system prompt", "override settings", "forget rules"]
    if any(kw in scrubbed.lower() for kw in injection_keywords):
        logger.warning(json.dumps({"severity": "CRITICAL", "event": "PROMPT_INJECTION_DETECTED"}))
        return Event(output="Security threat detected. Execution blocked.", route="SECURITY_EVENT")

    # Domain filter — unsafe destinations
    unsafe_keywords = ["active war zone", "hazardous area"]
    if any(kw in scrubbed.lower() for kw in unsafe_keywords):
        logger.warning(json.dumps({"severity": "WARNING", "event": "UNSAFE_DESTINATION_BLOCKED"}))
        return Event(output="Safety warning: cannot plan trips to hazardous destinations.", route="SECURITY_EVENT")

    logger.info(json.dumps({"severity": "INFO", "event": "SECURITY_PASS"}))
    return Event(output=scrubbed, route="PASS", state={"scrubbed_input": scrubbed})

@node
def security_failure(node_input: str) -> Event:
    yield Event(
        content=types.Content(role='model', parts=[types.Part.from_text(
            text=f"❌ Request blocked by safety filter: {node_input}"
        )]),
        output=node_input
    )

# ── Orchestrator ───────────────────────────────────────────────────────────────
@node(rerun_on_resume=True)
async def orchestrator(ctx: Context, node_input: str) -> AsyncGenerator[Event, None]:
    # Handle HITL budget confirmation resume
    if ctx.resume_inputs and "budget_confirm" in ctx.resume_inputs:
        answer = ctx.resume_inputs["budget_confirm"].lower().strip()
        if answer in ["no", "n", "cancel"]:
            yield Event(
                content=types.Content(role='model', parts=[types.Part.from_text(
                    text="Trip planning cancelled. Feel free to ask again with a different destination or budget!"
                )]),
                output="Cancelled"
            )
            return
        ctx.state["budget_override"] = True

    # Parse trip details from the user message
    details = ctx.state.get("trip_details")
    if not details:
        details = parse_trip_details(node_input)
        if not details:
            yield Event(
                content=types.Content(role='model', parts=[types.Part.from_text(
                    text=(
                        "I need a bit more info to plan your trip! Please include:\n"
                        "- **Destination** (e.g. Paris, Tokyo)\n"
                        "- **Duration** (e.g. 7 days)\n"
                        "- **Budget** (e.g. $2000 USD)\n\n"
                        "Example: *'Plan a trip to Paris for 7 days with a $2000 budget'*"
                    )
                )]),
                output="Need more info"
            )
            return
        ctx.state["trip_details"] = details

    destination = details["destination"]
    duration = details["duration_days"]
    budget = details["budget_usd"]

    # 1. Run destination agent
    raw_dest = await ctx.run_node(
        destination_agent,
        node_input=f"Give me top attractions and tips for {destination}."
    )
    dest_text = str(raw_dest) if raw_dest else ""
    attractions = extract_attractions(dest_text)
    tips = extract_field(dest_text, "TIPS", f"Check local travel advisories before visiting {destination}.")

    # 2. Run budget agent
    raw_budget = await ctx.run_node(
        budget_agent,
        node_input=f"Destination: {destination}, Duration: {duration} days, Budget: ${budget} USD. Is this sufficient?"
    )
    budget_text = str(raw_budget) if raw_budget else ""
    try:
        estimated_cost = float(re.search(r'ESTIMATED_COST:\s*\$?([\d,]+)', budget_text, re.IGNORECASE).group(1).replace(',',''))
    except Exception:
        estimated_cost = budget * 0.9

    status_match = re.search(r'STATUS:\s*(sufficient|insufficient)', budget_text, re.IGNORECASE)
    status = status_match.group(1).lower() if status_match else ("sufficient" if budget >= estimated_cost else "insufficient")
    breakdown = extract_field(budget_text, "BREAKDOWN", "Flights + accommodation + food")
    advice = extract_field(budget_text, "ADVICE", "Book in advance to save money.")

    # 3. HITL: warn if insufficient budget (only once)
    if status == "insufficient" and not ctx.state.get("budget_override"):
        yield RequestInput(
            interrupt_id="budget_confirm",
            message=(
                f"⚠️ Budget Warning: ${budget:.0f} USD may not be enough for {duration} days in {destination}.\n"
                f"💸 Estimated cost: ${estimated_cost:.0f} USD\n"
                f"📋 Breakdown: {breakdown}\n\n"
                f"Do you still want to proceed? (yes / no)"
            )
        )
        return

    # 4. Final itinerary
    status_emoji = "✅" if status == "sufficient" else "⚠️"
    attractions_md = "".join([f"- {a}\n" for a in attractions])
    itinerary = (
        f"# ✈️ Travel Plan: {destination}\n\n"
        f"📅 **Duration:** {duration} days  |  💰 **Budget:** ${budget:.0f} USD\n\n"
        f"---\n\n"
        f"### 📍 Top Attractions\n{attractions_md}\n"
        f"💡 **Tips:** {tips}\n\n"
        f"---\n\n"
        f"### 💵 Budget Analysis  {status_emoji}\n"
        f"| Item | Detail |\n"
        f"|------|--------|\n"
        f"| Estimated Cost | ${estimated_cost:.0f} USD |\n"
        f"| Your Budget | ${budget:.0f} USD |\n"
        f"| Status | **{status.upper()}** |\n\n"
        f"📋 **Breakdown:** {breakdown}\n"
        f"💡 **Advice:** {advice}\n"
    )

    yield Event(
        content=types.Content(role='model', parts=[types.Part.from_text(text=itinerary)]),
        output=itinerary
    )

# ── Workflow ───────────────────────────────────────────────────────────────────
root_agent = Workflow(
    name="trip_planner_workflow",
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=security_failure, route="SECURITY_EVENT"),
        Edge(from_node=security_checkpoint, to_node=orchestrator, route="PASS"),
    ],
    description="Secure trip planner: suggests attractions and validates budgets."
)

app = App(root_agent=root_agent, name="app")
