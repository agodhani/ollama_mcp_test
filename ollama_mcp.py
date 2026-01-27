from typing import Any
from datetime import datetime, timedelta
import sys
import os

import httpx
from mcp.server.fastmcp import FastMCP

import logging

# Add parent directory to path to import google_calendar
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from google_calendar import get_calendar_service

import pytz
from dateutil import parser as date_parser

# Setup logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[OLLAMA_MCP] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Initialize FastMCP server
logger.info("Initializing FastMCP server")
mcp = FastMCP("weather-and-calendar")

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"
# OLLAMA_API_BASE = "http://localhost:11434"
# OLLAMA_MODEL = "llama3.1:8b" 


# ===================== GOOGLE CALENDAR TOOLS =====================

def get_user_calendars() -> list[dict]:
    """Get list of user's calendars with id and name."""
    service = get_calendar_service()
    calendars = service.calendarList().list().execute().get("items", [])
    
    result = []
    for cal in calendars:
        result.append({
            "id": cal["id"],
            "name": cal.get("summary", "No Name")
        })
    return result


def extract_event_details(events: list) -> list[dict]:
    """Extract relevant details from calendar events."""
    event_dict = []
    for event in events:
        event_id = event.get('id')
        if not event_id:
            continue
        summary = event.get('summary', 'No Title')
        creator = event.get('creator', {}).get('email', 'Unknown')
        start = event.get('start', {})
        end = event.get('end', {})
        start_time = start.get('dateTime', 'N/A')
        end_time = end.get('dateTime', 'N/A')
        time_zone = start.get('timeZone', 'N/A')
        event_dict.append({
            'id': event_id,
            'summary': summary,
            'creator': creator,
            'start': start_time,
            'end': end_time,
            'timeZone': time_zone
        })
    return event_dict


def get_events_for_calendar(calendar_id: str, start_date: datetime | None = None, end_date: datetime | None = None) -> list[dict]:
    """
    Fetch events from a calendar within a specific date range.
    """
    service = get_calendar_service()

    # Default: fetch events for today if no dates provided
    if start_date is None:
        start_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    if end_date is None:
        end_date = start_date + timedelta(days=1)
    
    local_tz = pytz.timezone("America/New_York")

    # Helper: accept str or datetime (aware/naive) and return an aware datetime in local_tz
    def _to_localized(dt):
        # parse strings (handles trailing 'Z')
        if isinstance(dt, str):
            dt = date_parser.parse(dt)
        # If naive, assume it's in local_tz
        if dt.tzinfo is None:
            return local_tz.localize(dt)
        # If aware, convert to local_tz
        return dt.astimezone(local_tz)

    start_local = _to_localized(start_date)
    end_local = _to_localized(end_date)

    # Convert to RFC3339 (UTC) for the API
    time_min = start_local.astimezone(pytz.UTC).isoformat()
    time_max = end_local.astimezone(pytz.UTC).isoformat()

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime", 
    ).execute()

    events = events_result.get("items", [])
    return events

@mcp.tool()  
  
async def current_date() -> str:
    """Get the user's current date in YYYY-MM-DD format (Eastern Time).
    
    MANDATORY: ALWAYS call this FIRST before any calendar operations.
    Use this to compute relative dates (e.g., tomorrow = today + 1 day, next week = today + 7 days).
    
    Args:
        None
    
    Returns:
        str: Current date in format "YYYY-MM-DD" (e.g., "2026-01-26")
    """
    logger.info(f"current_date called ")
    eastern = pytz.timezone("America/New_York")
    return datetime.now(eastern).strftime("%Y-%m-%d")


@mcp.tool()
async def get_calendar_list() -> str:
    """Get list of all user calendars with their IDs and names.
    
    MANDATORY: Call this BEFORE any other calendar operations (get_calendar_events, create_calendar_event).
    Use to obtain the calendar_id parameter required for other calendar tools.
    If user does not specify a calendar, use the first available (primary).
    
    Args:
        None
    
    Returns:
        str: Formatted list of calendars, each with name and ID.
        Example:
            "Available Calendars:\n
            - My Calendar (ID: primary)\n
            - Work Events (ID: work@company.com)\n"
    """
    logger.info("get_calendar_list called")
    try:
        calendars = get_user_calendars()
        if not calendars:
            return "No calendars found."
        
        result = "Available Calendars:\n"
        for cal in calendars:
            result += f"- {cal['name']} (ID: {cal['id']})\n"
        logger.info(f"Retrieved {len(calendars)} calendars")
        return result
    except Exception as e:
        logger.error(f"Error getting calendar list: {e}")
        return f"Error fetching calendars: {str(e)}"


@mcp.tool()
async def get_calendar_events(calendar_id: str | None = None, start_date: str | None = None, end_date: str | None = None) -> str:
    """Retrieve events from a calendar within a specific date range.
    
    PREREQUISITES:
    - Call get_calendar_list() first to obtain calendar_id (or use primary if not specified).
    - Call current_date() to get today's date if start_date/end_date not provided by user.
    - Infer end_date as start_date + 1 day (daily) or + 7 days (weekly) if not specified.
    
    Args:
        calendar_id (str, optional): Calendar ID from get_calendar_list(). Defaults to primary calendar.
        start_date (str, optional): Start date in "YYYY-MM-DD" or ISO format (e.g., "2026-01-26").
        end_date (str, optional): End date in "YYYY-MM-DD" or ISO format (e.g., "2026-01-27").
    
    Returns:
        str: Formatted list of events with details (title, start, end, creator).
        Example:
            "Found 2 events:\n
            - Team Standup\n
              Start: 2026-01-26T10:00:00-05:00\n
              End: 2026-01-26T10:30:00-05:00\n
              Creator: user@example.com\n"
        Returns "No events found for the specified date range." if none match.
    """
    logger.info(f"get_calendar_events called with calendar_id={calendar_id}, start_date={start_date}, end_date={end_date}")
    try:
        # Get primary calendar if not specified
        if not calendar_id:
            cals = get_user_calendars()
            if not cals:
                return "No calendars available."
            calendar_id = cals[0]["id"]
            
        # Parse dates if provided
        start_dt = date_parser.parse(start_date) if start_date else None
        end_dt = date_parser.parse(end_date) if end_date else None
        
        events = get_events_for_calendar(calendar_id, start_dt, end_dt)
        event_details = extract_event_details(events)
        
        if not event_details:
            return f"No events found for the specified date range."
        
        result = f"Found {len(event_details)} events:\n"
        for event in event_details:
            result += f"\n- {event['summary']}\n"
            result += f"  Start: {event['start']}\n"
            result += f"  End: {event['end']}\n"
            result += f"  Creator: {event['creator']}\n"
        
        logger.info(f"Retrieved {len(event_details)} events")
        return result
    except Exception as e:
        logger.error(f"Error getting calendar events: {e}")
        return f"Error fetching events: {str(e)}"


@mcp.tool()
async def create_calendar_event(summary: str, start: str, end: str, calendar_id: str | None = None, timezone: str = "America/New_York") -> str:
    """Create a new calendar event with specified title, start time, and end time.
    
    PREREQUISITES:
    - Call get_calendar_list() first to obtain calendar_id (or use primary if not specified).
    - Call current_date() to infer dates if user provides relative time references.
    - Validate that start < end before calling this tool.
    
    Args:
        summary (str, required): Event title/description.
        start (str, required): Start time in "YYYY-MM-DDTHH:MM:SS" or ISO format (e.g., "2026-01-26T14:00:00").
        end (str, required): End time in "YYYY-MM-DDTHH:MM:SS" or ISO format (e.g., "2026-01-26T15:00:00").
        calendar_id (str, optional): Calendar ID from get_calendar_list(). Defaults to primary calendar.
        timezone (str, optional): IANA timezone name. Defaults to "America/New_York".
    
    Returns:
        str: Success message with event link or error description.
        Example:
            "Event 'Team Meeting' created successfully at https://calendar.google.com/calendar/u/0/r/eventedit/abc123"
        On error:
            "Error creating event: [error details]"
    """
    logger.info(f"create_calendar_event called with summary={summary}, start={start}, end={end}")
    try:
        service = get_calendar_service()
        
        # Get primary calendar if not specified
        if not calendar_id:
            cals = get_user_calendars()
            if not cals:
                return "No calendars available."
            calendar_id = cals[0]["id"]
        
        # Parse strings to datetimes
        start_dt = date_parser.parse(start) if isinstance(start, str) else start
        end_dt = date_parser.parse(end) if isinstance(end, str) else end

        # Ensure timezone-aware datetimes
        tz = pytz.timezone(timezone)
        if start_dt.tzinfo is None:
            start_dt = tz.localize(start_dt)
        else:
            start_dt = start_dt.astimezone(tz)
        if end_dt.tzinfo is None:
            end_dt = tz.localize(end_dt)
        else:
            end_dt = end_dt.astimezone(tz)

        event_body = {
            "summary": summary,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
        }

        created_event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
        logger.info(f"Event created with ID: {created_event.get('id')}")
        return f"Event '{summary}' created successfully at {created_event.get('htmlLink', 'calendar')}"
    except Exception as e:
        logger.error(f"Error creating event: {e}")
        return f"Error creating event: {str(e)}"


# ===================== WEATHER TOOLS =====================

async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


def format_alert(feature: dict) -> str:
    """Format an alert feature into a readable string."""
    props = feature["properties"]
    return f"""
Event: {props.get("event", "Unknown")}
Area: {props.get("areaDesc", "Unknown")}
Severity: {props.get("severity", "Unknown")}
Description: {props.get("description", "No description available")}
Instructions: {props.get("instruction", "No specific instructions provided")}
"""


# async def ask_ollama(prompt: str) -> str:
#     """Send a prompt to ollama and get a response."""
#     async with httpx.AsyncClient() as client:
#         try:
#             response = await client.post(
#                 f"{OLLAMA_API_BASE}/api/generate",
#                 json={
#                     "model": OLLAMA_MODEL,
#                     "prompt": prompt,
#                     "stream": False,
#                 },
#                 timeout=60.0,
#             )
#             response.raise_for_status()
#             data = response.json()
#             return data.get("response", "No response from ollama").strip()
#         except Exception as e:
#             return f"Error communicating with ollama: {str(e)}"

@mcp.tool()
async def get_alerts(state: str) -> str:
    """Retrieve active weather alerts for a US state.
    
    Args:
        state (str, required): Two-letter US state code (uppercase, e.g., "CA", "NY", "TX").
    
    Returns:
        str: Formatted list of active alerts with event, area, severity, description, and instructions.
        Example:
            "Event: Winter Storm Warning\n
            Area: Los Angeles County\n
            Severity: Moderate\n
            Description: Heavy snow expected...\n
            Instructions: Stay indoors...\n
            ---\n
            [next alert]"
        Returns "No active alerts for this state." if none found.
    """
    logger.info(f"get_alerts called with state={state}")
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        logger.warning(f"No data or features for state {state}")
        return "Unable to fetch alerts or no alerts found."

    if not data["features"]:
        logger.info(f"No active alerts for state {state}")
        return "No active alerts for this state."

    logger.info(f"Found {len(data['features'])} alerts for state {state}")
    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)


@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Retrieve weather forecast for a geographic location.
    
    Args:
        latitude (float, required): Latitude of the location (e.g., 40.7128 for New York).
        longitude (float, required): Longitude of the location (e.g., -74.0060 for New York).
    
    Returns:
        str: Formatted forecast periods (first 5 periods) with name, temperature, wind, and detailed forecast.
        Example:
            "Tonight:\n
            Temperature: 28°F\n
            Wind: 10 mph E\n
            Forecast: Mostly clear. Low 28F.\n
            ---\n
            Tuesday:\n
            Temperature: 45°F\n
            Wind: 5 mph N\n
            Forecast: Partly cloudy. High 45F.\n"
        Returns "Unable to fetch forecast data for this location." on error.
    """
    logger.info(f"get_forecast called with lat={latitude}, lon={longitude}")
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        logger.warning(f"Failed to fetch points data for lat={latitude}, lon={longitude}")
        return "Unable to fetch forecast data for this location."

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    logger.info(f"Fetching forecast from {forecast_url}")
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        logger.warning("Failed to fetch forecast data")
        return "Unable to fetch detailed forecast."

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    logger.info(f"Retrieved {len(periods)} forecast periods")
    forecasts = []
    for period in periods[:5]:  # Only show next 5 periods
        forecast = f"""
{period["name"]}:
Temperature: {period["temperature"]}°{period["temperatureUnit"]}
Wind: {period["windSpeed"]} {period["windDirection"]}
Forecast: {period["detailedForecast"]}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)


# @mcp.tool()
# async def analyze_with_ollama(text: str) -> str:
#     """Use ollama to analyze weather data or answer questions about it.

#     Args:
#         text: Text to analyze or question to answer
#     """
#     logger.info(f"analyze_with_ollama called with text length={len(text)}")
#     prompt = f"You are a helpful weather assistant. Please analyze the following and provide helpful insights:\n\n{text}\n\nProvide a concise, helpful response."
#     result = await ask_ollama(prompt)
#     logger.info(f"analyze_with_ollama returning result with length={len(result)}")
#     return result


def main():
    # If you want logs, send them to stderr, not stdout.
    logger.info("========== Starting MCP server (stdio) ==========")
    # logger.info(f"Model: {OLLAMA_MODEL}")
    logger.info(f"National Weather Services API Base: {NWS_API_BASE}")
    mcp.run(transport="stdio")



if __name__ == "__main__":
    main()
