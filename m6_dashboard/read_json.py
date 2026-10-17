import json

with open("m6_dashboard/mock_data/incidents.json", "r", encoding="utf-8") as file:
    data = json.load(file)

print("Total incidents:", len(data))
print("Incident IDs:", [incident["incident_id"] for incident in data])
print("Risk labels:", [incident["risk_label"] for incident in data])
