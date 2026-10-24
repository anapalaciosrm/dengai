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

    mode = cfg.get("travel_mode", "walk")
    lines = [f"*{title}: Team {team_id}*",
             f"{len(team)} sites. Start and finish: {start_name}.",
             "Tap a stop's link to navigate there from where you are.", ""]
    for n, row in enumerate(team.itertuples(), start=1):
        kind = ""
        if sites is not None and row.site_id in sites.index:
            kind = f" {sites.at[row.site_id, 'site_type']}"
        lines.append(f"{n}. {row.site_id}{kind}, about {clock(day_start, row.arrival_minute)}")
        lines.append(f"   {stop_link(row.lat, row.lon, mode)}")
    lines.append(f"Back to {start_name}: {stop_link(start_latlon[0], start_latlon[1], mode)}")
    lines += ["", "Whole route preview (best in the Google Maps app):"]
    for k, link in enumerate(links, start=1):
        label = "Route" if len(links) == 1 else f"Part {k} of {len(links)}"
        lines.append(f"{label}: {link}")
    lines += ["", "Reply with the stop numbers you inspected and what you found."]
    return "\n".join(lines), links


def stop_link(lat, lon, travel_mode="walk"):
    """Navigate from the phone's current location to one point. No origin, no waypoints,
    so it works in the Maps app and in mobile browsers, with no stop limit."""
    params = {"api": 1, "destination": f"{lat:.6f},{lon:.6f}",
              "travelmode": GOOGLE_MODES.get(str(travel_mode).lower(), "walking")}
    return "https://www.google.com/maps/dir/?" + urlencode(params, safe=",")


def plan_kml(plan, start_name, start_latlon, sites=None, paths=None, cfg=None, title="Dengai plan"):
    """KML file of the whole plan for Google My Maps (free): one folder per team with
    numbered stops and, if given, the street path. Import at mymaps.google.com."""
    from xml.sax.saxutils import escape
    day_start = (cfg or {}).get("day_start", "08:00")

    def placemark(name, lat, lon, desc=""):
        return (f"<Placemark><name>{escape(name)}</name><description>{escape(desc)}</description>"
                f"<Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point></Placemark>")

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             f"<name>{escape(title)}</name>",
             placemark(f"Start: {start_name}", start_latlon[0], start_latlon[1], "Puskesmas")]
    for team_id, team in plan.groupby("team_id"):
        parts.append(f"<Folder><name>Team {team_id}</name>")
        for n, row in enumerate(team.sort_values("visit_order").itertuples(), start=1):
            kind = sites.at[row.site_id, "site_type"] if sites is not None and row.site_id in sites.index else ""
            parts.append(placemark(f"T{team_id}-{n} {row.site_id}", row.lat, row.lon,
                                   f"{kind}, about {clock(day_start, row.arrival_minute)}"))
        line = (paths or {}).get(str(int(team_id)))
        if line:
            coords = " ".join(f"{lon:.6f},{lat:.6f},0" for lat, lon in line)
            parts.append(f"<Placemark><name>Team {team_id} route</name>"
                         f"<LineString><coordinates>{coords}</coordinates></LineString></Placemark>")
        parts.append("</Folder>")
    parts.append("</Document></kml>")
    return "\n".join(parts)


def whatsapp_link(text):
    """Link that opens WhatsApp with this message ready to send (user picks the chat)."""
    return "https://wa.me/?text=" + quote(text)
