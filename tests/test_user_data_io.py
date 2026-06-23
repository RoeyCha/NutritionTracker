import json
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from auth import create_access_token
from user_data_io import EXPORT_VERSION, export_csv, export_json


def _import_apply(client: TestClient, content: str, import_format: str = "json", **kwargs):
    payload = {
        "format": import_format,
        "content": content,
        "mode": kwargs.get("mode", "overwrite"),
    }
    if "resolutions" in kwargs:
        payload["resolutions"] = kwargs["resolutions"]
    return client.post(
        "/api/user-data/import",
        headers=client.auth_headers,
        json=payload,
    )


def test_export_json_contains_user_records(client: TestClient) -> None:
    response = client.get("/api/user-data/export?format=json", headers=client.auth_headers)

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert "nutrition-tracker-pytest_user.json" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["export_version"] == EXPORT_VERSION
    assert payload["username"] == "pytest_user"
    assert isinstance(payload["meals"], list)
    assert isinstance(payload["workouts"], list)
    assert len(payload["meals"]) >= 1
    assert len(payload["workouts"]) >= 1


def test_export_csv_has_record_type_header(client: TestClient) -> None:
    response = client.get("/api/user-data/export?format=csv", headers=client.auth_headers)

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert "nutrition-tracker-pytest_user.csv" in response.headers["content-disposition"]
    body = response.text.lstrip("\ufeff")
    lines = body.splitlines()
    assert lines[0].startswith("record_type")
    assert any("meal" in line for line in lines[1:])
    assert any("workout" in line for line in lines[1:])


def test_export_with_query_token_without_auth_header(client: TestClient) -> None:
    token = create_access_token(client.test_user)
    response = client.get(f"/api/user-data/export?format=json&token={token}")

    assert response.status_code == 200
    assert response.json()["username"] == "pytest_user"


def test_export_json_roundtrip_import(client: TestClient) -> None:
    exported = client.get(
        "/api/user-data/export?format=json",
        headers=client.auth_headers,
    ).json()

    exported["meals"].append(
        {
            "food_name": "Roundtrip meal",
            "calories": 410.0,
            "protein": 25.0,
            "carbohydrates": 30.0,
            "fats": 12.0,
            "logged_at": datetime.utcnow().isoformat(),
        }
    )

    import_response = _import_apply(
        client,
        json.dumps(exported, ensure_ascii=False),
        mode="overwrite",
    )

    assert import_response.status_code == 200
    assert import_response.json()["meals_imported"] == len(exported["meals"])

    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert "Roundtrip meal" in [meal["food_name"] for meal in summary["meals"]]


def test_export_csv_roundtrip_import(client: TestClient) -> None:
    csv_body = client.get(
        "/api/user-data/export?format=csv",
        headers=client.auth_headers,
    ).text.lstrip("\ufeff")

    logged_at = datetime.utcnow().isoformat()
    csv_body += (
        f"meal,{logged_at},,Roundtrip csv meal,,400,20,30,10,,,,,,,,,\n"
    )

    import_response = _import_apply(client, csv_body, import_format="csv", mode="overwrite")

    assert import_response.status_code == 200
    assert import_response.json()["meals_imported"] >= 1

    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert "Roundtrip csv meal" in [meal["food_name"] for meal in summary["meals"]]


def test_import_json_adds_meal(client: TestClient) -> None:
    payload = {
        "export_version": EXPORT_VERSION,
        "profile": {"name": "Pytest User"},
        "meals": [
            {
                "food_name": "Imported salad",
                "calories": 300.0,
                "protein": 20.0,
                "carbohydrates": 15.0,
                "fats": 10.0,
                "logged_at": datetime.utcnow().isoformat(),
            }
        ],
        "workouts": [],
        "daily_steps": [
            {
                "entry_date": date.today().isoformat(),
                "steps_count": 6000,
                "calories_burned": 180.0,
                "ai_explanation": "Imported steps",
            }
        ],
        "daily_weights": [
            {
                "entry_date": date.today().isoformat(),
                "weight_kg": 74.5,
            }
        ],
    }

    response = _import_apply(client, json.dumps(payload), mode="overwrite")

    assert response.status_code == 200
    result = response.json()
    assert result["meals_imported"] == 1
    assert result["steps_upserted"] == 1
    assert result["weights_upserted"] == 1

    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    meal_names = [meal["food_name"] for meal in summary["meals"]]
    assert "Imported salad" in meal_names
    assert summary["daily_steps"]["steps_count"] == 6000


def test_import_csv_adds_workout(client: TestClient) -> None:
    logged_at = datetime.utcnow().isoformat()
    csv_body = (
        "record_type,logged_at,entry_date,food_name,activity_type,calories,protein,carbohydrates,fats,calories_burned,steps_count,weight_kg,ai_explanation,name,email,gender,birth_date,height_cm,profile_weight_kg,initial_weight_kg\n"
        f"workout,{logged_at},,,Imported swim,,,,,260,,,,,,,,,\n"
    )

    response = _import_apply(client, csv_body, import_format="csv", mode="overwrite")

    assert response.status_code == 200
    assert response.json()["workouts_imported"] == 1

    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    activities = [workout["activity_type"] for workout in summary["workouts"]]
    assert "Imported swim" in activities


def test_import_preview_detects_meal_conflict(client: TestClient) -> None:
    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    existing_meal = summary["meals"][0]
    logged_at = existing_meal["logged_at"]

    payload = {
        "export_version": EXPORT_VERSION,
        "meals": [
            {
                "food_name": "Conflicting meal name",
                "calories": 999.0,
                "protein": 1.0,
                "carbohydrates": 1.0,
                "fats": 1.0,
                "logged_at": logged_at,
            }
        ],
        "workouts": [],
        "daily_steps": [],
        "daily_weights": [],
    }

    preview = client.post(
        "/api/user-data/import/preview?format=json",
        headers=client.auth_headers,
        content=json.dumps(payload),
    )

    assert preview.status_code == 200
    body = preview.json()
    assert body["summary"]["meals_conflict"] == 1
    assert body["has_conflicts"] is True
    assert body["conflicts"]["meals"][0]["existing"]["food_name"] == existing_meal["food_name"]
    assert body["conflicts"]["meals"][0]["imported"]["food_name"] == "Conflicting meal name"


def test_import_new_only_skips_conflicts_without_resolution(client: TestClient) -> None:
    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    existing_meal = summary["meals"][0]
    logged_at = existing_meal["logged_at"]

    payload = {
        "export_version": EXPORT_VERSION,
        "meals": [
            {
                "food_name": "Should not replace",
                "calories": 999.0,
                "protein": 1.0,
                "carbohydrates": 1.0,
                "fats": 1.0,
                "logged_at": logged_at,
            }
        ],
        "workouts": [],
        "daily_steps": [],
        "daily_weights": [],
    }

    response = _import_apply(client, json.dumps(payload), mode="new_only")

    assert response.status_code == 200
    assert response.json()["meals_imported"] == 0
    assert response.json()["meals_skipped"] == 1

    summary_after = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert summary_after["meals"][0]["food_name"] == existing_meal["food_name"]


def test_import_new_only_applies_conflict_resolution(client: TestClient) -> None:
    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    existing_meal = summary["meals"][0]
    logged_at = existing_meal["logged_at"]
    conflict_key = logged_at.replace("Z", "")
    if "." in conflict_key:
        conflict_key = conflict_key.split(".")[0]

    payload = {
        "export_version": EXPORT_VERSION,
        "meals": [
            {
                "food_name": "Resolved imported meal",
                "calories": 500.0,
                "protein": 30.0,
                "carbohydrates": 40.0,
                "fats": 15.0,
                "logged_at": logged_at,
            }
        ],
        "workouts": [],
        "daily_steps": [],
        "daily_weights": [],
    }

    preview = client.post(
        "/api/user-data/import/preview?format=json",
        headers=client.auth_headers,
        content=json.dumps(payload),
    ).json()
    conflict_key = preview["conflicts"]["meals"][0]["key"]

    response = _import_apply(
        client,
        json.dumps(payload),
        mode="new_only",
        resolutions={"meals": {conflict_key: "imported"}},
    )

    assert response.status_code == 200
    assert response.json()["meals_imported"] == 1

    summary_after = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert "Resolved imported meal" in [meal["food_name"] for meal in summary_after["meals"]]


def test_import_overwrite_removes_records_not_in_file(client: TestClient) -> None:
    summary_before = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert len(summary_before["meals"]) >= 1

    payload = {
        "export_version": EXPORT_VERSION,
        "meals": [
            {
                "food_name": "Only imported meal",
                "calories": 350.0,
                "protein": 20.0,
                "carbohydrates": 25.0,
                "fats": 12.0,
                "logged_at": datetime.utcnow().isoformat(),
            }
        ],
        "workouts": [],
        "daily_steps": [],
        "daily_weights": [],
    }

    response = _import_apply(client, json.dumps(payload), mode="overwrite")
    assert response.status_code == 200
    assert response.json()["meals_imported"] == 1

    export_after = client.get(
        "/api/user-data/export?format=json",
        headers=client.auth_headers,
    ).json()
    assert len(export_after["meals"]) == 1
    assert export_after["meals"][0]["food_name"] == "Only imported meal"


def test_import_overwrite_replaces_conflicting_meal(client: TestClient) -> None:
    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    existing_meal = summary["meals"][0]
    logged_at = existing_meal["logged_at"]

    payload = {
        "export_version": EXPORT_VERSION,
        "meals": [
            {
                "food_name": "Overwritten meal",
                "calories": 600.0,
                "protein": 40.0,
                "carbohydrates": 50.0,
                "fats": 20.0,
                "logged_at": logged_at,
            }
        ],
        "workouts": [],
        "daily_steps": [],
        "daily_weights": [],
    }

    response = _import_apply(client, json.dumps(payload), mode="overwrite")

    assert response.status_code == 200
    assert response.json()["meals_imported"] == 1

    summary_after = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert "Overwritten meal" in [meal["food_name"] for meal in summary_after["meals"]]


def test_import_new_only_adds_different_timestamp(client: TestClient) -> None:
    payload = {
        "export_version": EXPORT_VERSION,
        "meals": [
            {
                "food_name": "Future meal",
                "calories": 250.0,
                "protein": 10.0,
                "carbohydrates": 20.0,
                "fats": 8.0,
                "logged_at": (datetime.utcnow() + timedelta(days=2)).isoformat(),
            }
        ],
        "workouts": [],
        "daily_steps": [],
        "daily_weights": [],
    }

    preview = client.post(
        "/api/user-data/import/preview?format=json",
        headers=client.auth_headers,
        content=json.dumps(payload),
    ).json()
    assert preview["summary"]["meals_new"] == 1
    assert preview["has_conflicts"] is False

    response = _import_apply(client, json.dumps(payload), mode="new_only")
    assert response.status_code == 200
    assert response.json()["meals_imported"] == 1


def test_export_requires_auth(empty_client: TestClient) -> None:
    response = empty_client.get("/api/user-data/export?format=json")
    assert response.status_code == 401


def test_import_rejects_unsupported_version(client: TestClient) -> None:
    response = _import_apply(
        client,
        json.dumps({"export_version": 99, "meals": []}),
        mode="overwrite",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported export version: 99"
