from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

import logging, sys

# Setup logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='[OLLAMA_MCP] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Initialize FastMCP server
logger.info("Initializing FastMCP server")
mcp = FastMCP("weather")

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"
OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b" 


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


async def ask_ollama(prompt: str) -> str:
    """Send a prompt to ollama and get a response."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{OLLAMA_API_BASE}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "No response from ollama").strip()
        except Exception as e:
            return f"Error communicating with ollama: {str(e)}"

@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
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
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
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


@mcp.tool()
async def analyze_with_ollama(text: str) -> str:
    """Use ollama to analyze weather data or answer questions about it.

    Args:
        text: Text to analyze or question to answer
    """
    logger.info(f"analyze_with_ollama called with text length={len(text)}")
    prompt = f"You are a helpful weather assistant. Please analyze the following and provide helpful insights:\n\n{text}\n\nProvide a concise, helpful response."
    result = await ask_ollama(prompt)
    logger.info(f"analyze_with_ollama returning result with length={len(result)}")
    return result


def main():
    # If you want logs, send them to stderr, not stdout.
    logger.info("========== Starting MCP server (stdio) ==========")
    logger.info(f"Model: {OLLAMA_MODEL}")
    logger.info(f"NWS API Base: {NWS_API_BASE}")
    mcp.run(transport="stdio")



if __name__ == "__main__":
    main()
