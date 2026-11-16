"""NFL-only upgrades to Chip's line: EPA ratings, quarterback injuries, and weather.

EPA (expected points added) measures how good every play was, so it predicts future results better than
final scores. Data: nflverse (free, public, updated during the season).
"""
import io
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from . import config
from .teams import NFL_CODES

NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
CODE_TO_TEAM = {c: t for t, codes in NFL_CODES.items() for c in codes} | {"LA": "Los Angeles Rams"}

# Stadium coordinates; indoor = dome or retractable roof (weather ignored).
STADIUMS = {
    "Arizona Cardinals": (33.5276, -112.2626, True), "Atlanta Falcons": (33.7554, -84.4008, True),
    "Baltimore Ravens": (39.2780, -76.6227, False), "Buffalo Bills": (42.7738, -78.7870, False),
    "Carolina Panthers": (35.2258, -80.8528, False), "Chicago Bears": (41.8623, -87.6167, False),
    "Cincinnati Bengals": (39.0954, -84.5160, False), "Cleveland Browns": (41.5061, -81.6995, False),
    "Dallas Cowboys": (32.7473, -97.0945, True), "Denver Broncos": (39.7439, -105.0201, False),
    "Detroit Lions": (42.3400, -83.0456, True), "Green Bay Packers": (44.5013, -88.0622, False),
    "Houston Texans": (29.6847, -95.4107, True), "Indianapolis Colts": (39.7601, -86.1639, True),
    "Jacksonville Jaguars": (30.3239, -81.6373, False), "Kansas City Chiefs": (39.0489, -94.4839, False),
    "Las Vegas Raiders": (36.0909, -115.1833, True), "Los Angeles Chargers": (33.9535, -118.3392, True),
    "Los Angeles Rams": (33.9535, -118.3392, True), "Miami Dolphins": (25.9580, -80.2389, False),
    "Minnesota Vikings": (44.9737, -93.2581, True), "New England Patriots": (42.0909, -71.2643, False),
    "New Orleans Saints": (29.9511, -90.0812, True), "New York Giants": (40.8135, -74.0745, False),
    "New York Jets": (40.8135, -74.0745, False), "Philadelphia Eagles": (39.9008, -75.1675, False),
    "Pittsburgh Steelers": (40.4468, -80.0158, False), "San Francisco 49ers": (37.4030, -121.9700, False),
    "Seattle Seahawks": (47.5952, -122.3316, False), "Tampa Bay Buccaneers": (27.9759, -82.5033, False),
    "Tennessee Titans": (36.1665, -86.7713, False), "Washington Commanders": (38.9078, -76.8645, False),
}


def _csv(url, get=requests.get, **kw):
    r = get(url, timeout=120)
    r.raise_for_status()
    comp = "gzip" if url.endswith(".gz") or r.content[:2] == b"\x1f\x8b" else None
    return pd.read_csv(io.BytesIO(r.content), compression=comp, low_memory=False, **kw)


def load_pbp(year, get=requests.get):
    cols = {"game_id", "week", "posteam", "defteam", "home_team", "away_team", "epa", "play_type",
            "qb_dropback", "passer_player_id", "passer_player_name", "game_date", "season_type"}
    df = _csv(f"{NFLVERSE}/pbp/play_by_play_{year}.csv.gz", get, usecols=lambda c: c in cols)
    df = df[df["season_type"] == "REG"] if "season_type" in df else df
    return df[df["play_type"].isin(["pass", "run"]) & df["epa"].notna()]


def load_injuries(year, get=requests.get):
    return _csv(f"{NFLVERSE}/injuries/injuries_{year}.csv", get)


def epa_games(pbp):
    """One row per game: home/away full names and the 'EPA margin' (home offense EPA - away offense EPA), in points."""
    out = []
    for gid, g in pbp.groupby("game_id"):
        h, a = g["home_team"].iloc[0], g["away_team"].iloc[0]
        ht, at = CODE_TO_TEAM.get(h), CODE_TO_TEAM.get(a)
        if not ht or not at:
            continue
        he = g.loc[g["posteam"] == h, "epa"].sum()
        ae = g.loc[g["posteam"] == a, "epa"].sum()
        out.append({"home": ht, "away": at, "hs": he, "as": ae, "neutral": False,
                    "date": f"{g['game_date'].iloc[0]}T17:00:00Z"})
    return out


def qb_adjustments(pbp, inj):
    """Points to subtract from a team whose starting QB is Out/Doubtful (half for Questionable).

    Starter = most dropbacks in the team's last 3 games. Value = (starter EPA/dropback - backup baseline)
    x the team's dropbacks per game, clamped to [1.5, 8] points.
    """
    adj, notes = {}, {}
    if pbp.empty or inj is None or inj.empty:
        return adj, notes
    drop = pbp[pbp["qb_dropback"] == 1]
    latest_wk = inj["week"].max()
    rep = inj[(inj["week"] == latest_wk) & (inj["position"] == "QB")]
    for code, team in CODE_TO_TEAM.items():
        td = drop[drop["posteam"] == code]
        if td.empty:
            continue
        recent_games = td["game_id"].drop_duplicates().tail(3)
        recent = td[td["game_id"].isin(recent_games)]
        if recent["passer_player_id"].dropna().empty:
            continue
        starter = recent["passer_player_id"].value_counts().idxmax()
        name = recent.loc[recent["passer_player_id"] == starter, "passer_player_name"].iloc[0]
        row = rep[(rep["gsis_id"] == starter)]
        if row.empty:
            continue
        status = str(row["report_status"].iloc[0])
        weight = 1.0 if status in ("Out", "Doubtful") else (0.5 if status == "Questionable" else 0.0)
        if not weight:
            continue
        sd = td[td["passer_player_id"] == starter]
        per_db = sd["epa"].mean()
        dbs_per_game = len(td) / max(td["game_id"].nunique(), 1)
        value = float(np.clip((per_db - config.BACKUP_QB_EPA) * dbs_per_game, 1.5, 8.0))
        adj[team] = adj.get(team, 0.0) + value * weight
        notes[team] = f"QB {name} {status.upper()} (-{value * weight:.1f})"
    return adj, notes


def weather_for(home_team, kickoff_iso, get=requests.get):
    """Forecast at kickoff for outdoor stadiums: dict(wind_mph, precip_mm, temp_f, total_adj, label) or None."""
    st = STADIUMS.get(home_team)
    if not st or st[2]:
        return None
    lat, lon, _ = st
    try:
        r = get("https://api.open-meteo.com/v1/forecast", timeout=30, params={
            "latitude": lat, "longitude": lon, "hourly": "temperature_2m,precipitation,wind_speed_10m",
            "wind_speed_unit": "mph", "temperature_unit": "fahrenheit", "timezone": "UTC", "forecast_days": 10})
        r.raise_for_status()
        h = r.json()["hourly"]
    except Exception:
        return None
    ko = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    key = ko.strftime("%Y-%m-%dT%H:00")
    if key not in h["time"]:
        return None
    i = h["time"].index(key)
    span = slice(i, min(i + 3, len(h["time"])))  # the first ~3 hours of the game
    def avg(k):
        vals = [v for v in h.get(k, [])[span] if v is not None]
        return float(np.mean(vals)) if vals else None
    wind, rain, temp = avg("wind_speed_10m"), avg("precipitation"), avg("temperature_2m")
    if wind is None or temp is None:
        return None  # too far out - the forecast has no numbers for kickoff yet
    rain = rain or 0.0
    adj, tags = 0.0, []
    if wind >= 12:
        adj -= min(6.0, (wind - 12) * 0.3 + 1.0); tags.append(f"WIND {wind:.0f} MPH")
    if rain >= 1.0:
        adj -= 1.5; tags.append("RAIN" if temp > 34 else "SNOW")
    if temp <= 20:
        adj -= 1.0; tags.append(f"{temp:.0f}°F")
    return {"wind_mph": round(wind), "precip_mm": round(rain, 1), "temp_f": round(temp), "total_adj": round(adj, 1),
            "label": " · ".join(tags)}
