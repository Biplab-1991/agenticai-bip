from mcp.server.fastmcp import FastMCP
# Initialize the FastMCP server with name "Weather"
mcp = FastMCP("Weather")



@mcp.tool()
async def get_weather(location: str) -> str:
    """Get the current weather for a specified location."""
    print(f"Weather tool: Getting weather for {location}")
    # In a real application, this would call a live weather API (e.g., OpenWeatherMap, AccuWeather).
    # For this simulation, we return hardcoded responses.
    if "New York" in location:
        return "It's always sunny in New York (simulated)."
    elif "London" in location:
        return "It's currently cloudy with a chance of rain in London (simulated)."
    else:
        return f"Weather data for {location} is not available (simulated)."

if __name__ == "__main__":
    # This block runs the server when the script is executed directly.
    # It uses 'stdio' transport and defines a specific port for communication.
    print("Starting Weather MCP server on port 8001 (default)...")
    mcp.run(transport="stdio")