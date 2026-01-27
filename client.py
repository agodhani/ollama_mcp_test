import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

import httpx
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

# Setup logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[CLIENT] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# ---- Configure these ----
SERVER_CMD = ["python", "ollama_mcp.py"] 
OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_MODEL = "gcal:latest" 
# -------------------------


def _tool_to_ollama_schema(tool: Any) -> Dict[str, Any]:
    """
    Convert a FastMCP tool definition to an Ollama tool schema.
    FastMCP tools typically expose name, description, and an input schema.
    """
    name = getattr(tool, "name", None) or tool.get("name")
    description = getattr(tool, "description", None) or tool.get("description", "")

    # FastMCP often uses inputSchema (JSON Schema-like) for tool args
    input_schema = (
        getattr(tool, "inputSchema", None)
        or getattr(tool, "input_schema", None)
        or tool.get("inputSchema")
        or tool.get("input_schema")
        or {"type": "object", "properties": {}}
    )

    # Ollama expects tools in a "function calling" format.
    # See Ollama tool-calling docs.
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": input_schema,
        },
    }


def _result_to_text(result: Any) -> str:
    """
    Normalize FastMCP call_tool result into text.
    FastMCP examples/tests show result.content[0].text or result.data.
    """
    if result is None:
        return ""

    # Common: result.data
    data = getattr(result, "data", None)
    if data is not None:
        return str(data)

    # Common: result.content is a list of parts with .text
    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        parts = []
        for part in content:
            txt = getattr(part, "text", None)
            if txt is not None:
                parts.append(txt)
            else:
                # fallback: stringify unknown part
                parts.append(str(part))
        return "\n".join(parts)

    return str(result)


async def ollama_chat(
    client: httpx.AsyncClient,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Call Ollama /api/chat with tool definitions.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "tools": tools,
        "stream": False,
        # You can add options here if desired:
        # "options": {"temperature": 0.2},
    }
    logger.info(f"Ollama payload: {json.dumps(payload, indent=2)[:500]}...")
    
    try:
        r = await client.post(
            f"{OLLAMA_API_BASE}/api/chat",
            json=payload,
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Ollama request failed: {e}")
        logger.error(f"Response text: {r.text if 'r' in locals() else 'N/A'}")
        raise


async def main():
    logger.info("========== Starting MCP Client ==========")
    logger.info(f"Server command: {SERVER_CMD}")
    logger.info(f"Ollama API Base: {OLLAMA_API_BASE}")
    logger.info(f"Ollama Model: {OLLAMA_MODEL}")
    
    # 1) Connect to MCP server over stdio (spawns subprocess)
    logger.info("Connecting to MCP server...")
    transport = StdioTransport(command=SERVER_CMD[0], args=SERVER_CMD[1:])

    async with Client(transport) as mcp_client:
        logger.info("Connected to MCP server")
        # 2) Discover tools
        logger.info("Discovering tools...")
        tools = await mcp_client.list_tools()
        logger.info(f"Found {len(tools)} tools")
        ollama_tools = [_tool_to_ollama_schema(t) for t in tools]

        tool_names = [getattr(t, "name", None) or t.get("name") for t in tools]
        print("Connected. Tools available:", ", ".join([n for n in tool_names if n]))
        logger.info(f"Tools: {', '.join([n for n in tool_names if n])}")

        # 3) Start interactive loop
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Follow system instructions and use the provided tools to assist the user. ALWAYS CALL CURRENT DATE TOOL FIRST"
                ),
            }
        ]

        async with httpx.AsyncClient() as ollama_http:
            logger.info("Entering main conversation loop")
            while True:
                user_text = input("\nYou> ").strip()
                if user_text.lower() in {"exit", "quit"}:
                    logger.info("User exited")
                    break
                if not user_text:
                    continue

                logger.info(f"User input: {user_text[:100]}..." if len(user_text) > 100 else f"User input: {user_text}")
                messages.append({"role": "user", "content": user_text})

                # 4) Tool-calling loop:
                # Keep calling Ollama until it returns a final assistant message with no tool calls.
                logger.info("Starting tool-calling loop")
                for loop_idx in range(10):  # hard stop to avoid infinite loops
                    logger.info(f"Tool loop iteration {loop_idx + 1}")
                    resp = await ollama_chat(ollama_http, messages, ollama_tools)

                    msg = resp.get("message", {})
                    role = msg.get("role", "assistant")
                    content = msg.get("content", "") or ""
                    tool_calls = msg.get("tool_calls") or []

                    logger.info(f"Ollama response: role={role}, content_length={len(content)}, tool_calls={len(tool_calls)}")
                    
                    # If Ollama produced normal assistant text, store it
                    if content:
                        messages.append({"role": role, "content": content})
                        logger.info(f"Added assistant message to conversation")

                    # If no tool calls, we are done with this user turn
                    if not tool_calls:
                        logger.info("No tool calls, conversation turn complete")
                        if content:
                            print(f"\nAssistant> {content}")
                        else:
                            # Some models may return empty content; avoid printing blank
                            print("\nAssistant> (no content)")
                        break

                    # Otherwise execute tool calls and feed results back
                    logger.info(f"Executing {len(tool_calls)} tool calls")
                    for tc_idx, tc in enumerate(tool_calls):
                        fn = (tc.get("function") or {})
                        tool_name = fn.get("name")
                        args = fn.get("arguments")

                        logger.info(f"Tool call {tc_idx + 1}: {tool_name} with args={args}")
                        
                        # Ollama may return arguments as dict or as JSON string depending on model
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                                logger.info(f"Parsed JSON arguments: {args}")
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse JSON arguments, using raw: {args}")
                                args = {"_raw": args}

                        if not isinstance(args, dict):
                            args = {}

                        # Execute MCP tool
                        logger.info(f"Calling MCP tool: {tool_name}")
                        tool_result = await mcp_client.call_tool(tool_name, args)
                        tool_text = _result_to_text(tool_result)
                        logger.info(f"Tool result length: {len(tool_text)}")

                        # Add tool result message back to conversation
                        # This format mirrors common tool-calling chat conventions.
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.get("id"),
                                "name": tool_name,
                                "content": tool_text,
                            }
                        )
                        logger.info(f"Added tool result to conversation")

                else:
                    logger.warning("Tool loop limit reached")
                    print("\nAssistant> Tool loop limit reached; aborting this turn.")

if __name__ == "__main__":
    asyncio.run(main())
