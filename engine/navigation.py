"""Turn a team's plan into things a field team can use on a phone, for free.

* Google Maps directions LINKS (not the paid API). Opening a link is free.
  Google allows up to 9 waypoints per link in the Maps app (3 in mobile browsers),
  so long routes are split into parts: part 2 starts where part 1 ends.
  Source: Google Maps URLs guide, Directions action (developers.google.com/maps/documentation/urls).
* A plain text message with the ordered stops and the links, ready to share on WhatsApp.
  wa.me/?text=... opens WhatsApp with the message filled in; the coordinator picks the chat.

Used by app.py. Nothing here calls the internet.
"""

from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

# Our travel_mode values -> Google Maps travelmode values.
GOOGLE_MODES = {"walk": "walking", "moto": "two-wheeler", "motorbike": "two-wheeler",
                "car": "driving", "bike": "bicycling"}


def maps_links(points, travel_mode="walk", max_waypoints=9):
    """Split an ordered list of (lat, lon) into Google Maps directions links.

    Each link: origin, up to max_waypoints stops, destination. The next link starts
    at the previous destination, so the parts chain into one route.
    """
    mode = GOOGLE_MODES.get(str(travel_mode).lower(), "walking")
    step = max_waypoints + 1          # points covered by one link after its origin
    links = []
    i = 0
    while i < len(points) - 1:
        part = points[i:i + step + 1]
        params = {
            "api": 1,
            "origin": f"{part[0][0]:.6f},{part[0][1]:.6f}",
            "destination": f"{part[-1][0]:.6f},{part[-1][1]:.6f}",
            "travelmode": mode,
        }
        middle = part[1:-1]
        if middle:
            params["waypoints"] = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in middle)
        links.append("https://www.google.com/maps/dir/?" + urlencode(params, safe=","))
        i += step
    return links


def clock(day_start, minutes):
    """'08:00' plus minutes -> '08:31'. If day_start is not a time, show '+31 min'."""
    try:
        t = datetime.strptime(str(day_start), "%H:%M") + timedelta(minutes=float(minutes))
        return t.strftime("%H:%M")
    except ValueError:
        return f"+{minutes:.0f} min"


def team_message(team_id, team, start_name, start_latlon, cfg, sites=None, title="Dengai"):
    """WhatsApp ready text for one team: ordered stops, times, and map links.

    team: rows of the plan table for this team (site_id, lat, lon, arrival_minute).
    """
    team = team.sort_values("visit_order")
    points = [start_latlon] + list(zip(team["lat"], team["lon"])) + [start_latlon]
    links = maps_links(points, cfg.get("travel_mode", "walk"), int(cfg.get("nav_max_waypoints", 9)))
    day_start = cfg.get("day_start", "08:00")

    lines = [f"*{title}: Team {team_id}*",
             f"{len(team)} sites. Start and finish: {start_name}.", ""]
    for n, row in enumerate(team.itertuples(), start=1):
        kind = ""
        if sites is not None and row.site_id in sites.index:
            kind = f" {sites.at[row.site_id, 'site_type']}"
        lines.append(f"{n}. {row.site_id}{kind}, about {clock(day_start, row.arrival_minute)}")
    lines.append("")
    if len(links) == 1:
        lines.append(f"Route in Google Maps: {links[0]}")
    else:
        for k, link in enumerate(links, start=1):
            lines.append(f"Route part {k} of {len(links)}: {link}")
    lines += ["", "Reply with the stop numbers you inspected and what you found."]
    return "\n".join(lines), links


def whatsapp_link(text):
    """Link that opens WhatsApp with this message ready to send (user picks the chat)."""
    return "https://wa.me/?text=" + quote(text)
