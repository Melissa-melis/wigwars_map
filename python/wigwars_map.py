#!/usr/bin/env python3
"""WigWars map builder
Copyright (c) 2026 Mélissa (melis) and contributors

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "wigwars_data.json"
HTML_FILE = HERE / "wigwars-map-local.html"

LINDEN_COORDS = (
    "https://cap.secondlife.com/cap/0/d661249b-2b5a-4436-966a-3d3b8d7a574f"
    "?var=coords&sim_name={name}"
)
GRIDSURVEY = "https://api.gridsurvey.com/simquery.php?region={name}"

SLURL_RE = re.compile(
    r"""
    (?:https?://maps\.secondlife\.com/secondlife/|secondlife://)?
    (?P<region>[^/]+)
    /(?P<x>\d+(?:\.\d+)?)
    /(?P<y>\d+(?:\.\d+)?)
    (?:/(?P<z>\d+(?:\.\d+)?))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

ICON_PX = 28


# read the json, fill in missing fields so old files still work
def load_data() -> dict:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    data.setdefault("center", [1062, 1128])
    data.setdefault("zoom", 3)
    data.setdefault("colonies", [])
    data.setdefault("specials", [])
    data.pop("default_icon", None)
    data.pop("fortresses", None)
    data.pop("ships", None)
    data.pop("icons", None)
    data.pop("product_icons", None)
    for item in data["colonies"] + data["specials"]:
        item.setdefault("name", "")
        item.setdefault("prod", "")
        item.setdefault("faction", "")
        item.setdefault("note", "")
        item.setdefault("icon", "")
    return data


# write the json back, same shape we expect on the next run
def save_data(data: dict) -> None:
    DATA_FILE.write_text(
        json.dumps(
            {
                "center": data["center"],
                "zoom": data["zoom"],
                "colonies": data["colonies"],
                "specials": data["specials"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


# prompt, keep the default if they just hit enter
def ask(prompt: str, default: str = "") -> str:
    extra = f" [{default}]" if default else ""
    value = input(f"{prompt}{extra}: ").strip()
    return value if value else default


# pull region + local xyz out of a slurl or loose text
def parse_slurl(text: str) -> dict | None:
    text = text.strip()
    probe = text.replace(" ", "%20") if "secondlife.com" in text.lower() else text
    # maps links use %20 in the region name, plain text usually does not
    m = SLURL_RE.search(probe)
    if m:
        return {
            "region": urllib.parse.unquote(m.group("region").replace("%20", " ")),
            "local_x": float(m.group("x")),
            "local_y": float(m.group("y")),
            "local_z": float(m.group("z") or 0),
        }
    parts = re.split(r"[/,]\s*|\s+", text.strip())
    if (
        len(parts) >= 3
        and parts[-2].replace(".", "", 1).isdigit()
        and parts[-1].replace(".", "", 1).isdigit()
    ):
        if len(parts) >= 4 and parts[-3].replace(".", "", 1).isdigit():
            region, lx, ly, lz = " ".join(parts[:-3]), parts[-3], parts[-2], parts[-1]
        else:
            region, lx, ly, lz = " ".join(parts[:-2]), parts[-2], parts[-1], "0"
        if region:
            return {
                "region": urllib.parse.unquote(region.replace("%20", " ")),
                "local_x": float(lx),
                "local_y": float(ly),
                "local_z": float(lz),
            }
    return None


# simple GET, we only need the body
def http_get(url: str, timeout: float = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "WigWarsMap/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# grid x/y for a sim name — Linden first, GridSurvey if it dies
def lookup_region(name: str) -> tuple[int, int]:
    encoded = urllib.parse.quote(name.strip())
    try:
        body = http_get(LINDEN_COORDS.format(name=encoded))
        m = re.search(r"'x'\s*:\s*(\d+)\s*,\s*'y'\s*:\s*(\d+)", body)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception as exc:
        print(f"  Linden lookup failed ({exc}), trying GridSurvey...")
    try:
        body = http_get(GRIDSURVEY.format(name=encoded))
        xs = re.search(r"^x\s+(\d+)\s*$", body, re.M)
        ys = re.search(r"^y\s+(\d+)\s*$", body, re.M)
        if xs and ys:
            return int(xs.group(1)), int(ys.group(1))
    except Exception as exc:
        print(f"  GridSurvey lookup failed ({exc})")
    raise RuntimeError(f"Could not resolve region '{name}'. Check the spelling.")


# secondlife:// link that opens the installed viewer
def slurl_of(region: str, lx, ly, lz) -> str:
    """Viewer protocol SLurl — opens the default Second Life / Firestorm client."""
    name = (region or "").strip()
    path = urllib.parse.quote(name, safe="-._~ ").replace(" ", "%20")
    # keep hyphens, only encode the spaces
    return (
        f"secondlife://{path}/"
        f"{int(float(lx))}/{int(float(ly))}/{int(float(lz))}"
    )


# human readable Region/x/y/z for the popup
def slurl_label(region: str, lx, ly, lz) -> str:
    return (
        f"{(region or '').strip()}/"
        f"{int(float(lx))}/{int(float(ly))}/{int(float(lz))}"
    )


# make a string safe to drop inside generated JS
def js_escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


# true if the icon is a remote image instead of an emoji
def is_url(value: str) -> bool:
    return str(value).startswith(("http://", "https://"))


# print colonies and specials
def list_markers(data: dict) -> None:
    print("\n  Colonies")
    if not data["colonies"]:
        print("    (none)")
    for i, c in enumerate(data["colonies"], 1):
        bits = [x for x in (c.get("prod"), c.get("faction"), c.get("note")) if x]
        print(
            f"    {i:3d}. {c['name']:28s}  {c.get('x')},{c.get('y')}  "
            f"{c.get('icon') or 'red'}  {' · '.join(bits)}"
        )
    print("  Specials")
    if not data["specials"]:
        print("    (none)")
    for i, s in enumerate(data["specials"], 1):
        sl = (
            f"{s.get('region','')}/{int(s.get('local_x') or 0)}/"
            f"{int(s.get('local_y') or 0)}/{int(s.get('local_z') or 0)}"
        )
        bits = [x for x in (s.get("prod"), s.get("faction"), s.get("note")) if x]
        print(
            f"    {i:3d}. {s.get('name','?'):28s}  {sl}  "
            f"{s.get('icon') or 'red'}  {' · '.join(bits)}"
        )
    print(f"\n  {len(data['colonies'])} colonies, {len(data['specials'])} specials")


# ask product / faction / note
def extras(item: dict | None = None) -> tuple[str, str, str]:
    item = item or {}
    return (
        ask("Product", item.get("prod") or ""),
        ask("Faction", item.get("faction") or ""),
        ask("Remarks", item.get("note") or ""),
    )


# let them pick a row by number
def pick_item(bucket: list, label: str) -> dict | None:
    if not bucket:
        print(f"  no {label}")
        return None
    for i, item in enumerate(bucket, 1):
        print(f"    {i:3d}. {item.get('name') or item.get('region')}")
    raw = ask("Number (0 = cancel)")
    if not raw.isdigit():
        print("  cancelled")
        return None
    n = int(raw)
    if n < 1 or n > len(bucket):
        print("  cancelled")
        return None
    return bucket[n - 1]


# change product / faction / note on an existing pin
def edit_marker(bucket: list, label: str) -> None:
    item = pick_item(bucket, label)
    if not item:
        return
    print(
        f"  editing {item.get('name') or item.get('region')}\n"
        f"  current  prod={item.get('prod')!r}  faction={item.get('faction')!r}  note={item.get('note')!r}"
    )
    prod, faction, note = extras(item)
    item["prod"] = prod
    item["faction"] = faction
    item["note"] = note
    print("  saved")


# add a region-center colony (icon still goes in the json)
def add_colony(data: dict) -> None:
    raw = ask("Region name (or SLurl)")
    if not raw:
        print("  cancelled")
        return
    parsed = parse_slurl(raw)
    name = parsed["region"] if parsed else raw
    print(f"  looking up '{name}' ...")
    x, y = lookup_region(name)
    print(f"  grid x={x}  y={y}")
    prod, faction, note = extras()
    item = {
        "name": name,
        "x": x,
        "y": y,
        "prod": prod,
        "faction": faction,
        "note": note,
        "icon": "",
    }
    for old in data["colonies"]:
        if old["name"].lower() == name.lower():
            old.update(item)
            print(f"  updated colony {name} — set icon in JSON")
            return
    data["colonies"].append(item)
    print(f"  added colony {name} — set icon in JSON")


# add a precise in-sim marker from a slurl
def add_special(data: dict) -> None:
    raw = ask("SLurl or Region/x/y/z")
    if not raw:
        print("  cancelled")
        return
    parsed = parse_slurl(raw)
    if not parsed:
        region = raw
        lx, ly, lz = ask("Local X (0-255)"), ask("Local Y (0-255)"), ask("Local Z", "23")
        if not lx or not ly:
            print("  cancelled")
            return
        parsed = {
            "region": region,
            "local_x": float(lx),
            "local_y": float(ly),
            "local_z": float(lz or 0),
        }
    print(f"  looking up '{parsed['region']}' ...")
    x, y = lookup_region(parsed["region"])
    print(f"  grid x={x}  y={y}  + local {parsed['local_x']}/{parsed['local_y']}")
    name = ask("Name", parsed["region"])
    prod, faction, note = extras()
    data["specials"].append(
        {
            "name": name,
            "region": parsed["region"],
            "x": x,
            "y": y,
            "local_x": parsed["local_x"],
            "local_y": parsed["local_y"],
            "local_z": parsed["local_z"],
            "prod": prod,
            "faction": faction,
            "note": note,
            "icon": "",
        }
    )
    print("  added special — set icon in JSON")


# delete one entry from a list
def remove_from(bucket: list, label: str) -> None:
    if not bucket:
        print(f"  no {label}")
        return
    for i, item in enumerate(bucket, 1):
        print(f"    {i:3d}. {item.get('name') or item.get('region')}")
    raw = ask("Number to remove (0 = cancel)")
    if not raw.isdigit():
        print("  cancelled")
        return
    n = int(raw)
    if n < 1 or n > len(bucket):
        print("  cancelled")
        return
    gone = bucket.pop(n - 1)
    print(f"  removed {gone.get('name') or gone.get('region')}")


# resolve a name/slurl and print coords, don't save anything
def lookup_only() -> None:
    raw = ask("Region name or SLurl")
    if not raw:
        return
    parsed = parse_slurl(raw)
    name = parsed["region"] if parsed else raw
    x, y = lookup_region(name)
    print(f"  region '{name}'  grid x={x}  y={y}")
    if parsed:
        mx = x + parsed["local_x"] / 256
        my = y + parsed["local_y"] / 256
        print(f"  map x={mx:.6f}  y={my:.6f}   marker([{my:.6f}, {mx:.6f}])")
        print(f"  {slurl_of(name, parsed['local_x'], parsed['local_y'], parsed['local_z'])}")
    else:
        print(f"  region-center marker([{y + 0.5}, {x + 0.5}])")


# leaflet icon for a colony (emoji, image url, or red pin)
def pin_js(icon: str, var_name: str) -> str:
    px = ICON_PX
    if icon and is_url(icon):
        return (
            f"    const {var_name} = L.icon({{"
            f'iconUrl:"{js_escape(icon)}",iconSize:[{px},{px}],iconAnchor:[{px//2},{px}]}});'
        )
    if icon:
        return (
            f"    const {var_name} = L.divIcon({{className:'emo-marker',"
            f"html:'<div class=\"emo\">{js_escape(icon)}</div>',"
            f"iconSize:[{px},{px}],iconAnchor:[{px//2},{px}]}});"
        )
    return (
        f"    const {var_name} = L.divIcon({{className:'emo-marker',"
        f"html:'<div class=\"redpin\"></div>',"
        f"iconSize:[22,30],iconAnchor:[11,30]}});"
    )


# yellow triangle used for specials
def warn_js(icon: str, var_name: str) -> str:
    mark = js_escape(icon) if icon and not is_url(icon) else "!"
    return (
        f"    const {var_name} = L.divIcon({{className:'emo-marker',"
        f"html:'<div class=\"warn\"><span>{mark}</span></div>',"
        f"iconSize:[32,30],iconAnchor:[16,30]}});"
    )


# popup body + the viewer slurl
def popup_html(
    title: str,
    rows: list[tuple[str, str]],
    slurl: str = "",
    slurl_text: str = "",
) -> str:
    parts = [f"<h4>{js_escape(title)}</h4>"]
    for label, value in rows:
        if value:
            parts.append(f"{js_escape(label)}: {js_escape(value)}<br>")
    if slurl:
        label = slurl_text or slurl
        parts.append(
            '<a class="slurl" href="'
            + js_escape(slurl)
            + '" title="Open in the default Second Life viewer">'
            + "SLurl: "
            + js_escape(label)
            + "</a>"
        )
    return "".join(parts)



# stamp json into the static html map
def generate_html(data: dict) -> None:
    cy, cx = data["center"]
    zoom = data.get("zoom", 3)
    pin_defs = [pin_js("", "PIN_RED")]
    used = {"": "PIN_RED"}

    # reuse the same leaflet icon if we already built it
    def pin_var(icon: str) -> str:
        key = icon or ""
        if key in used:
            return used[key]
        name = "PIN_" + str(len(used))
        used[key] = name
        pin_defs.append(pin_js(icon, name))
        return name

    lines = []
    for c in data["colonies"]:
        var = pin_var(c.get("icon") or "")
        region = c.get("name") or "Colony"
        pop = popup_html(
            region,
            [("Product", c.get("prod") or ""), ("Faction", c.get("faction") or ""), ("Note", c.get("note") or "")],
            slurl_of(region, 128, 128, 23),
            # colony = region center, not a specific landing point
            slurl_label(region, 128, 128, 23),
        )
        prod = js_escape((c.get("prod") or "").strip())
        icon = js_escape((c.get("icon") or "").strip())
        lines.append(
            f'    placeMarker([{c["y"]}+0.5, {c["x"]}+0.5], {{icon:{var}}}, "{js_escape(pop)}", "{prod}", "{icon}");'
            # leaflet latlng is [gridY, gridX], +0.5 puts it in the sim middle
        )
    for i, s in enumerate(data["specials"]):
        var = f"WARN_{i}"
        pin_defs.append(warn_js(s.get("icon") or "", var))
        mx = f"({s['x']} + {s['local_x']} / 256)"
        # local 0-255 sits inside the 256m sim
        my = f"({s['y']} + {s['local_y']} / 256)"
        region = s.get("region") or s.get("name", "")
        sl = slurl_of(region, s["local_x"], s["local_y"], s.get("local_z") or 0)
        sl_text = slurl_label(region, s["local_x"], s["local_y"], s.get("local_z") or 0)
        pop = popup_html(
            s.get("name") or "Special",
            [
                ("Product", s.get("prod") or ""),
                ("Faction", s.get("faction") or ""),
                ("Note", s.get("note") or ""),
            ],
            sl,
            sl_text,
        )
        prod = js_escape((s.get("prod") or "").strip())
        icon = js_escape((s.get("icon") or "").strip())
        lines.append(
            f'    placeMarker([{my}, {mx}], {{icon:{var}, zIndexOffset:1000}}, "{js_escape(pop)}", "{prod}", "{icon}");'
        )

    n_col, n_sp = len(data["colonies"]), len(data["specials"])
    hint = f"WigWars Map — {n_col} colonies"
    if n_sp:
        hint += f", {n_sp} special{'s' if n_sp != 1 else ''}"
    hint += f" · grid center {cx}, {cy}"

    html = FILTER_HTML_TEMPLATE
    html = html.replace("@@ICON_PX@@", str(ICON_PX))
    html = html.replace("@@HINT@@", js_escape(hint))
    html = html.replace("@@CY@@", str(cy))
    html = html.replace("@@CX@@", str(cx))
    html = html.replace("@@ZOOM@@", str(zoom))
    html = html.replace("@@PIN_DEFS@@", chr(10).join(pin_defs))
    html = html.replace("@@MARKERS@@", chr(10).join(lines))
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"  wrote {HTML_FILE.name}  ({n_col} colonies, {n_sp} specials)")


FILTER_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>wigwars colonies map</title>
  <link rel="stylesheet" href="https://maps.secondlife.com/_styles/sl.mapapi2.css">
  <script src="https://maps.secondlife.com/_scripts/sl.mapapi2.js"></script>
  <style>
    html, body, #map { margin: 0; height: 100%; width: 100%; background: #1d475f; }
    .leaflet-marker-icon { filter: initial; }
    .leaflet-control-container { display: none !important; }
    .hint, .disclaimer {
      font: 12px/1.4 system-ui, sans-serif; color: #eee;
      background: rgba(0,0,0,.55); padding: 8px 10px; border-radius: 8px;
    }
    .hint {
      position: absolute; z-index: 1000; left: 12px; bottom: 12px;
    }
    .left-stack {
      position: absolute; z-index: 1000; left: 12px; top: 12px;
      width: min(480px, calc(100% - 24px));
      display: flex; flex-direction: column; gap: 8px;
      pointer-events: none;
    }
    .left-stack > * { pointer-events: auto; }
    .disclaimer {
      color: #ccc; font-size: 11px;
    }
    .filter-panel {
      position: absolute; z-index: 1000; top: 12px; right: 12px;
      width: min(260px, calc(100% - 24px));
      font: 12px/1.4 system-ui, sans-serif; color: #eee;
      background: rgba(0,0,0,.62); padding: 10px 10px 8px; border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0,0,0,.35);
      backdrop-filter: blur(4px);
    }
    .filter-head {
      display: flex; align-items: center; justify-content: space-between;
      gap: 8px; margin-bottom: 8px;
    }
    .filter-head h3 {
      margin: 0; font-size: 13px; font-weight: 650; letter-spacing: .02em;
    }
    .filter-head button, .filter-actions button {
      appearance: none; border: 1px solid rgba(255,255,255,.28);
      background: rgba(255,255,255,.08); color: #eee;
      border-radius: 6px; padding: 3px 8px; font: 11px/1.2 system-ui, sans-serif;
      cursor: pointer;
    }
    .filter-head button:hover, .filter-actions button:hover {
      background: rgba(255,255,255,.16);
    }
    .filter-actions { display: flex; gap: 6px; margin-bottom: 8px; }
    .filter-actions button { flex: 1; padding: 5px 8px; }
    .filter-list {
      max-height: min(52vh, 420px); overflow: auto;
      display: flex; flex-direction: column; gap: 2px;
      padding-right: 2px;
    }
    .filter-item {
      display: flex; align-items: center; gap: 8px;
      padding: 3px 4px; border-radius: 5px; cursor: pointer;
      user-select: none;
    }
    .filter-item:hover { background: rgba(255,255,255,.08); }
    .filter-item input { margin: 0; accent-color: #7ec8e3; }
    .filter-ico {
      width: 1.4em; text-align: center; flex: 0 0 1.4em;
      font-size: 14px; line-height: 1;
    }
    .filter-ico img { width: 14px; height: 14px; object-fit: contain; vertical-align: middle; }
    .filter-name { flex: 1; text-transform: capitalize; }
    .filter-count { color: #aaa; font-size: 11px; }
    .filter-note {
      margin-top: 7px; color: #bbb; font-size: 10px;
    }
    .filter-panel.collapsed .filter-actions,
    .filter-panel.collapsed .filter-list,
    .filter-panel.collapsed .filter-note { display: none; }
    .leaflet-popup-content a.slurl {
      display: inline-block;
      margin-top: 6px;
      color: #9ad7ff;
      text-decoration: none;
      font-weight: 600;
    }
    .leaflet-popup-content a.slurl:hover { text-decoration: underline; }
    .emo-marker { background: none !important; border: none !important; }
    .emo {
      width: @@ICON_PX@@px; height: @@ICON_PX@@px; border-radius: 50%;
      background: rgba(8,18,28,.9); border: 1px solid rgba(255,255,255,.4);
      display: flex; align-items: center; justify-content: center;
      font-size: 20px; line-height: 1;
      box-shadow: 0 2px 8px rgba(0,0,0,.5);
    }
    .redpin {
      width: 16px; height: 16px; background: #e23b2e;
      border: 2px solid #fff; border-radius: 50% 50% 50% 0;
      transform: rotate(-45deg);
      box-shadow: 0 2px 6px rgba(0,0,0,.45);
    }
    .warn {
      width: 32px; height: 30px;
      background: #f0c400;
      clip-path: polygon(50% 0%, 0% 100%, 100% 100%);
      display: flex; align-items: flex-end; justify-content: center;
      filter: drop-shadow(0 2px 4px rgba(0,0,0,.55));
    }
    .warn span {
      color: #111; font: 700 13px/1 system-ui, sans-serif;
      padding-bottom: 3px;
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="hint" id="hint">@@HINT@@</div>
  <div class="left-stack">
  <div class="disclaimer">This map is provided as is, without any guarantee, and is not affiliated with WigWars or N+K products. For any questions or update requests, please contact me in-world: Mélissa (melis).</div>
  </div>
  <aside class="filter-panel" id="filter-panel">
    <div class="filter-head">
      <h3>Goods filter</h3>
      <button type="button" id="filter-toggle" aria-expanded="true">hide</button>
    </div>
    <div class="filter-actions">
      <button type="button" id="filter-all">Select all</button>
      <button type="button" id="filter-none">Select none</button>
    </div>
    <div class="filter-list" id="filter-list"></div>
    <div class="filter-note">Markers with no product stay visible.</div>
  </aside>
  <script>
    const map = SLMap(document.getElementById("map"));
    map.setView([@@CY@@, @@CX@@], @@ZOOM@@);
    const allMarkers = [];
    const hintBase = document.getElementById("hint").textContent;

    // drop a colony/special pin coming from python
    function placeMarker(latlng, opts, popup, prod, icon) {
      const marker = L.marker(latlng, opts).bindPopup(popup);
      allMarkers.push({
        marker: marker,
        prod: (prod || "").trim(),
        icon: (icon || "").trim(),
        visible: true
      });
      marker.addTo(map);
    }

@@PIN_DEFS@@
@@MARKERS@@

    // icon is an image url?
    function isUrl(value) {
      return new RegExp('^https?://', 'i').test(value || "");
    }

    // collect products present on the map for the filter
    function goodsFromMarkers() {
      const seen = new Map();
      for (const item of allMarkers) {
        if (!item.prod) continue;
        if (!seen.has(item.prod)) {
          seen.set(item.prod, { name: item.prod, icon: item.icon, count: 0 });
        }
        const row = seen.get(item.prod);
        row.count += 1;
        if (!row.icon && item.icon) row.icon = item.icon;
      }
      return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name));
    }

    // tiny icon next to a filter row
    function iconHtml(icon) {
      if (!icon) return "";
      if (isUrl(icon)) return '<img src="' + icon.replace(/"/g, "&quot;") + '" alt="">';
      return icon;
    }

    const goods = goodsFromMarkers();
    const listEl = document.getElementById("filter-list");
    const selected = new Set(goods.map((g) => g.name));

    // draw the goods checkboxes
    function renderList() {
      listEl.innerHTML = goods.map((g) => {
        const id = "good-" + encodeURIComponent(g.name);
        const checked = selected.has(g.name) ? " checked" : "";
        return '<label class="filter-item" for="' + id + '">'
          + '<input type="checkbox" id="' + id + '" data-good="' + g.name.replace(/"/g, "&quot;") + '"' + checked + '>'
          + '<span class="filter-ico">' + iconHtml(g.icon) + '</span>'
          + '<span class="filter-name">' + g.name + '</span>'
          + '<span class="filter-count">' + g.count + '</span>'
          + '</label>';
      }).join("");
    }

    // hide unchecked goods — empty product always stays
    function applyFilter() {
      let visible = 0;
      for (const item of allMarkers) {
        const show = !item.prod || selected.has(item.prod);
        // no product → always on
        if (show) {
          if (!item.visible) {
            item.marker.addTo(map);
            item.visible = true;
          }
          visible += 1;
        } else if (item.visible) {
          map.removeLayer(item.marker);
          item.visible = false;
        }
      }
      document.getElementById("hint").textContent = hintBase + " · showing " + visible + "/" + allMarkers.length;
    }

    listEl.addEventListener("change", (ev) => {
      const box = ev.target;
      if (!box || !box.matches("input[type=checkbox][data-good]")) return;
      if (box.checked) selected.add(box.getAttribute("data-good"));
      else selected.delete(box.getAttribute("data-good"));
      applyFilter();
    });

    document.getElementById("filter-all").addEventListener("click", () => {
      goods.forEach((g) => selected.add(g.name));
      renderList();
      applyFilter();
    });

    document.getElementById("filter-none").addEventListener("click", () => {
      selected.clear();
      renderList();
      applyFilter();
    });

    document.getElementById("filter-toggle").addEventListener("click", () => {
      const panel = document.getElementById("filter-panel");
      const btn = document.getElementById("filter-toggle");
      const collapsed = panel.classList.toggle("collapsed");
      btn.textContent = collapsed ? "show" : "hide";
      btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });

    renderList();
    applyFilter();

    document.addEventListener("click", (ev) => {
      const link = ev.target && ev.target.closest ? ev.target.closest("a.slurl") : null;
      if (!link) return;
      const href = link.getAttribute("href") || "";
      if (!href.toLowerCase().startsWith("secondlife:")) return;
      ev.preventDefault();
      ev.stopPropagation();
      window.location.href = href;
    }, true);
  </script>
</body>
</html>
"""


# text menu
def menu() -> None:
    print(
        f"""
================================================
 WigWars map builder
 {DATA_FILE.name}  /  {HTML_FILE.name}
 Set icon in JSON (emoji or image URL). Empty = red pin.
================================================
  1  list
  2  add colony
  3  remove colony
  4  add special marker
  5  remove special marker
  6  generate HTML
  7  lookup coords
  8  edit colony (product / faction / note)
  9  edit special (product / faction / note)
  0  quit
"""
    )


# cli: --html just rebuilds, otherwise run the menu
def main() -> None:
    data = load_data()
    if len(sys.argv) > 1 and sys.argv[1] in ("--html", "--generate"):
        save_data(data)
        generate_html(data)
        return
    generate_html(data)
    print(f"Loaded {len(data['colonies'])} colonies, {len(data['specials'])} specials")
    while True:
        menu()
        choice = ask("Choice").lower()
        try:
            if choice in ("0", "q", "quit", "exit"):
                save_data(data)
                generate_html(data)
                print("bye")
                return
            actions = {
                "1": lambda: list_markers(data),
                "2": lambda: add_colony(data),
                "3": lambda: remove_from(data["colonies"], "colonies"),
                "4": lambda: add_special(data),
                "5": lambda: remove_from(data["specials"], "specials"),
                "6": lambda: None,
                "7": lookup_only,
                "8": lambda: edit_marker(data["colonies"], "colonies"),
                "9": lambda: edit_marker(data["specials"], "specials"),
            }
            if choice not in actions:
                print("  unknown choice")
                continue
            actions[choice]()
            if choice in ("2", "3", "4", "5", "6", "8", "9"):
                save_data(data)
                generate_html(data)
        except KeyboardInterrupt:
            print("\n  cancelled")
        except Exception as exc:
            print(f"  error: {exc}")


if __name__ == "__main__":
    main()
