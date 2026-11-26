"""Revisioned drawing responses associated with one immutable India handoff."""
from .model import panel_shape


def register(data, answers):
    requests = [{"id": "check/" + row["id"], "description": row["description"], "status": row["status"]}
                for row in data.get("checks", []) if row["status"] != "pass"]
    requests.extend({"id": "connection/" + row["id"], "description": row["type"], "status": "detail pending"}
                    for row in data.get("connections", []) if not row.get("parts"))
    return {"requests": requests, "panels": [p["id"] for p in data.get("panels", [])], "answers": answers}


def revise(data, old_answers, response):
    """Reapply the current responses to the original source. Reopening removes the overlay."""
    answer = dict(response)
    key = answer["request_id"]
    source = register(data, old_answers)
    index = {r["id"] for r in source["requests"]}
    opening = key.startswith("opening/")
    if opening:
        if len(key) == len("opening/") or answer.get("panel") not in source["panels"]:
            raise ValueError("A labelled opening needs a host panel from the original design")
    elif key not in index:
        raise ValueError("Choose a request in the design register")
    if answer["action"] == "confirm opening":
        if not opening or len(answer.get("outline") or []) < 3:
            raise ValueError("A confirmed opening requires a host and at least three perimeter points in mm")
    elif answer.get("outline"):
        raise ValueError("Only a confirmed opening can change the drawing perimeter")
    previous = {r["request_id"]: r for r in old_answers}
    if answer["action"] == "reopen" and key not in previous:
        raise ValueError("Choose a request with a saved response to reopen it")
    if key in previous and opening and previous[key].get("panel") != answer.get("panel"):
        raise ValueError("Use the same host panel when revising an existing opening")
    if answer["action"] == "confirm opening":
        answer["geometry_reviewer"] = answer["reviewer"]
    elif answer["action"] == "information" and previous.get(key, {}).get("outline"):
        answer["outline"] = previous[key]["outline"]
        answer["geometry_reviewer"] = previous[key]["geometry_reviewer"]
    previous[key] = answer
    panels = {p["id"]: p for p in data.get("panels", [])}
    for row in previous.values():
        label = f"{row['request_id']} · {row['reviewer']} · {row['action']}"
        data.setdefault("assumptions", []).append(f"{label}. {row['note']}")
        if row.get("outline"):
            host = panels[row["panel"]]
            host.setdefault("openings", []).append(row["outline"])
            # Checks every ring against the actual host plane, boundary and other holes.
            panel_shape(host)
            review_id = "OPENBIM-" + row["request_id"]
            if any(item["id"] == review_id for item in data.get("checks", [])):
                raise ValueError("Choose an opening mark distinct from source check identifiers")
            data.setdefault("checks", []).append({"id": review_id, "status": "review",
                "description": f"Coordinate {row['request_id']} on {host['id']} with the native structural design.",
                "reference": "Architectural opening accepted for drawings by " + row["geometry_reviewer"]})
            host.setdefault("checks", []).append(review_id)
    return list(previous.values())
