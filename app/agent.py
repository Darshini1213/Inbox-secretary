# ruff: noqa
import os
import re
import json
import logging
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import AgentTool, request_input
from google.adk.workflow import Workflow, Edge, START, node
from google.adk import Context
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams, StdioServerParameters
from google.adk.tools import McpToolset

from app.config import config

# Configure local logger for security auditing
security_logger = logging.getLogger("security_audit")

# ---------------------------------------------------------------------------
# State Schema
# ---------------------------------------------------------------------------
class InboxState(BaseModel):
    user_request: str = Field(default="", description="The original request from the user.")
    latest_email: str = Field(default="", description="The text of the email being processed or draft.")
    action_status: str = Field(default="", description="Status of email drafting or calendar scheduling.")
    security_status: str = Field(default="UNKNOWN", description="Security checkpoint status.")

# ---------------------------------------------------------------------------
# MCP Toolset Wiring
# ---------------------------------------------------------------------------
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"],
        )
    )
)

# ---------------------------------------------------------------------------
# Sub-Agents (Phase 3: Wire McpToolset into at least 2 agents)
# ---------------------------------------------------------------------------
email_agent = LlmAgent(
    name="email_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Email Specialist. Your job is to analyze incoming email requests, "
        "classify emails, and draft high-quality responses. "
        "Use the 'list_emails' tool to read incoming messages and 'send_email_reply' tool "
        "to reply to them when directed. "
        "Always draft the reply first."
    ),
    tools=[mcp_toolset],
)

calendar_agent = LlmAgent(
    name="calendar_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Calendar Specialist. Your job is to parse scheduling details "
        "(date, time, event description) from queries. "
        "Use the 'schedule_calendar_event' tool to schedule events in the calendar."
    ),
    tools=[mcp_toolset],
)

# ---------------------------------------------------------------------------
# Orchestrator Agent
# ---------------------------------------------------------------------------
orchestrator_agent = LlmAgent(
    name="orchestrator_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Orchestrator of the Inbox Secretary. "
        "You handle requests about emails and calendar events. "
        "You have access to two specialized sub-agents: 'email_agent' (for email drafting) "
        "and 'calendar_agent' (for calendar events). "
        "Call the appropriate agent(s) as tools to get the task done. "
        "CRITICAL: Before sending any reply or scheduling any event, "
        "you MUST call the 'request_input' tool to ask the user for approval. "
        "Only proceed with actions if the user explicitly approves. "
        "Summarize the final action taken to the user."
    ),
    tools=[AgentTool(agent=email_agent), AgentTool(agent=calendar_agent), request_input],
)

# ---------------------------------------------------------------------------
# Workflow Nodes & Security Checkpoint (Phase 4)
# ---------------------------------------------------------------------------
@node
async def security_checkpoint(ctx: Context, node_input: str) -> str:
    """Performs PII scrubbing, prompt injection detection, and domain rules validation."""
    ctx.state["user_request"] = node_input
    
    # 1. PII Scrubbing (Regex for phone, SSN, Credit Card)
    scrubbed = node_input
    scrubbed = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]", scrubbed)
    scrubbed = re.sub(r"\b\d{3}-\d{3}-\d{4}\b", "[PHONE_REDACTED]", scrubbed)
    scrubbed = re.sub(r"\b(?:\d[ -]*?){13,16}\b", "[CREDIT_CARD_REDACTED]", scrubbed)
    
    pii_scrubbed_flag = scrubbed != node_input
    
    # 2. Prompt Injection Detection
    text_lower = scrubbed.lower()
    injections = [
        "ignore previous instructions", 
        "system override", 
        "bypass security", 
        "sudo ", 
        "ignore rules", 
        "act as developer"
    ]
    injection_detected = False
    for keyword in injections:
        if keyword in text_lower:
            injection_detected = True
            break
            
    # 3. Domain-Specific Rule: Spam Content Filter
    spam_keywords = ["viagra", "lottery winner", "claim your prize", "free cash bonus"]
    spam_detected = any(spam in text_lower for spam in spam_keywords)
    
    # Decision Routing and Structured JSON Audit Logging
    audit_data = {
        "event": "security_audit_check",
        "pii_scrubbed": pii_scrubbed_flag,
        "injection_detected": injection_detected,
        "spam_detected": spam_detected,
        "severity": "INFO"
    }
    
    if injection_detected:
        audit_data["severity"] = "CRITICAL"
        audit_data["message"] = "Prompt injection attempt detected!"
        security_logger.error(json.dumps(audit_data))
        ctx.state["security_status"] = "VIOLATION"
        ctx.route = "SECURITY_EVENT"
        return "Security Violation: Unauthorized command injection."
        
    if spam_detected:
        audit_data["severity"] = "WARNING"
        audit_data["message"] = "Spam content detected in request."
        security_logger.warning(json.dumps(audit_data))
        ctx.state["security_status"] = "VIOLATION"
        ctx.route = "SECURITY_EVENT"
        return "Security Violation: Prohibited spam content."

    if pii_scrubbed_flag:
        audit_data["severity"] = "WARNING"
        audit_data["message"] = "PII elements scrubbed from request."
        security_logger.warning(json.dumps(audit_data))
    else:
        security_logger.info(json.dumps(audit_data))
        
    ctx.state["security_status"] = "SAFE"
    ctx.state["latest_email"] = scrubbed
    ctx.route = "SAFE"
    return scrubbed

@node
async def security_event_node(ctx: Context, node_input: str) -> str:
    """Handles blocked requests."""
    print("STATE TYPE:", type(ctx.state))
    print("STATE:", ctx.state)
    return f"ACCESS DENIED: {node_input}"
@node
async def final_output_node(ctx: Context, node_input: str) -> str:
    """Summarizes actions taken."""
    status = ctx.state.get("action_status") or "Request completed."
    return f"Secretary Output: {node_input}\nStatus: {status}"

# ---------------------------------------------------------------------------
# Workflow Definition
# ---------------------------------------------------------------------------
edges = [
    Edge(from_node=START, to_node=security_checkpoint),
    Edge(from_node=security_checkpoint, to_node=security_event_node, route="SECURITY_EVENT"),
    Edge(from_node=security_checkpoint, to_node=orchestrator_agent, route="SAFE"),
    Edge(from_node=security_event_node, to_node=final_output_node),
    Edge(from_node=orchestrator_agent, to_node=final_output_node),
]

root_agent = Workflow(
    name="inbox_secretary_workflow",
    state_schema=InboxState,
    edges=edges,
)

app = App(
    root_agent=root_agent,
    name="app",
)
