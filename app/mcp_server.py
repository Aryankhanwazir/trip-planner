import sys
from fastmcp import FastMCP

# Initialize MCP Server
mcp = FastMCP("Trip Planner Helper")

@mcp.tool()
def get_attraction_reviews(attraction: str) -> str:
    """Gets user reviews and rating for a specific tourist attraction.
    
    Args:
        attraction: The name of the attraction (e.g. 'Eiffel Tower').
    """
    print(f"Executing get_attraction_reviews for {attraction}", file=sys.stderr)
    # Simple mock reviews
    reviews = {
        "eiffel tower": "⭐⭐⭐⭐⭐ - Breathtaking views, long lines but absolutely worth it!",
        "louvre museum": "⭐⭐⭐⭐ - Incredible art collection, extremely crowded. Go early!",
        "colosseum": "⭐⭐⭐⭐⭐ - Magnificent history. Getting a guide is recommended.",
        "statue of liberty": "⭐⭐⭐⭐ - Great experience, ferry ride was beautiful.",
        "machu picchu": "⭐⭐⭐⭐⭐ - Magical and mystical, bucket list item!"
    }
    return reviews.get(attraction.lower().strip(), f"⭐⭐⭐⭐ - Beautiful place, highly recommended by visitors! (4.5/5 stars)")

@mcp.tool()
def get_exchange_rate(currency: str) -> float:
    """Gets the mock exchange rate to USD for a given currency code.
    
    Args:
        currency: The 3-letter currency code (e.g. 'EUR', 'GBP').
    """
    print(f"Executing get_exchange_rate for {currency}", file=sys.stderr)
    rates = {
        "EUR": 1.09, # 1 EUR = 1.09 USD
        "GBP": 1.27, # 1 GBP = 1.27 USD
        "JPY": 0.0063, # 1 JPY = 0.0063 USD
        "CAD": 0.73, # 1 CAD = 0.73 USD
        "AUD": 0.66, # 1 AUD = 0.66 USD
    }
    return rates.get(currency.upper().strip(), 1.0)

@mcp.tool()
def get_flight_estimate(origin: str, destination: str) -> float:
    """Gets a flight cost estimate (roundtrip) in USD.
    
    Args:
        origin: Departure city/airport.
        destination: Arrival city/airport.
    """
    print(f"Executing get_flight_estimate from {origin} to {destination}", file=sys.stderr)
    # Generate a reproducible mock price based on letters
    val = sum(ord(c) for c in origin.lower() + destination.lower()) % 400 + 350
    return float(val)

@mcp.tool()
def get_safety_index(destination: str) -> str:
    """Gets safety information and advisory level for a destination.
    
    Args:
        destination: City or country name.
    """
    print(f"Executing get_safety_index for {destination}", file=sys.stderr)
    low_safety = ["active war zone", "hazardous area"]
    if any(kw in destination.lower() for kw in low_safety):
        return "Advisory Level 4: Do Not Travel. Extreme risk."
    
    moderate_safety = ["paris", "rome", "london", "tokyo", "new york"]
    if any(city in destination.lower() for city in moderate_safety):
        return "Advisory Level 1: Exercise Normal Precautions. Standard tourist safety rules apply."
    
    return "Advisory Level 2: Exercise Increased Caution. Pay attention to local media and pickpocket hotspots."

if __name__ == "__main__":
    mcp.run(transport="stdio")
