# Ollama MCP - Weather & Calendar Integration

This project demonstrates Model Context Protocol (MCP) integration with Ollama, providing both weather and calendar management capabilities through a unified MCP server.

## Architecture

- **ollama_mcp.py**: FastMCP server exposing weather and calendar tools
- **client.py**: Client that connects to the MCP server and uses Ollama for intelligent tool orchestration
- **google_calendar.py**: Google Calendar OAuth2 authentication and service setup

## Available Tools

### Weather Tools
- `get_alerts(state)` - Get active weather alerts for a US state
- `get_forecast(latitude, longitude)` - Get weather forecast for a location
- `analyze_with_ollama(text)` - Analyze weather data using Ollama

### Calendar Tools
- `get_calendar_list()` - List all available calendars
- `get_calendar_events(calendar_id, start_date, end_date)` - Retrieve events from a calendar
- `create_calendar_event(summary, start, end, calendar_id, timezone)` - Create a new calendar event

## Setup

1. Ensure Ollama is running locally on port 11434
2. Set up Google Calendar authentication (requires credentials.json)
3. Install dependencies: `pip install -e .`

## Running

```bash
# Start the MCP server
python ollama_mcp.py

# In another terminal, run the client
python client.py
```

The client provides an interactive chat interface where you can request weather information or manage calendar events using natural language.
