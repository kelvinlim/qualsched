"""YAML import/export never writes the API token into the file."""

from app.importexport import build_legacy_yaml, parse_config, parse_token_file

YAML = """
account:
  DATA_CENTER: yul1
  DEFAULT_DIRECTORY: POOL_x
  LIBRARY_ID: GR_lib
  VERIFY: true
project:
  NAME: Sleep
  SURVEY_ID: SV_1
  MESSAGE_ID: MS_sms
  MESSAGE_ID_EMAIL: MS_email
  MAILING_LIST_ID: CG_list
  TIMEZONE: America/Chicago
  MINUTES_EXPIRE: 60
embedded_data:
  StartDate: '2026-09-01'
  SurveysScheduled: 0
  TimeSlots: 800,1200
  ContactMethod: sms
  DeleteUnsent: 0
  NumDays: 7
  ExpireMinutes: 60
  LogData: '[]'
  TimeZone: America/Chicago
email_header:
  FROM_EMAIL: study@umn.edu
  FROM_NAME: Study
  REPLY_TO_EMAIL: study@umn.edu
  SUBJECT: Survey
"""


def test_parse_and_export_roundtrip_has_no_token():
    preview = parse_config(YAML, "config_qualtrics_sleep.yaml")
    assert preview.account.dataCenter == "yul1"
    assert preview.project.name == "Sleep"
    assert preview.tokenFound is False

    out = build_legacy_yaml(preview.account, preview.project)
    assert "QUALTRICS_APITOKEN" not in out
    assert "yul1" in out
    assert "SV_1" in out


def test_parse_token_file():
    assert parse_token_file("QUALTRICS_APITOKEN=abc123\n") == "abc123"
    assert parse_token_file("# comment\nDATACENTER=ca1\n") is None


def test_import_confirm_stores_token_encrypted_not_in_config(ctx):
    client, _, _ = ctx
    preview = parse_config(YAML, "config.yaml")
    body = {
        "account": preview.account.model_dump(),
        "project": preview.project.model_dump(),
        "token": "imported-secret-token",
    }
    r = client.post("/api/import/confirm", json=body)
    assert r.status_code == 200, r.text
    assert "imported-secret-token" not in r.text
    account_id = r.json()["accounts"][0]["id"]
    assert client.get(f"/api/accounts/{account_id}/has-token").json() is True

    exported = client.get(
        f"/api/accounts/{account_id}/projects/{preview.project.id}/export"
    )
    assert exported.status_code == 200
    assert "imported-secret-token" not in exported.text
    assert "QUALTRICS_APITOKEN" not in exported.text


def test_preview_endpoint(ctx):
    client, _, _ = ctx
    r = client.post(
        "/api/import/preview-text",
        data={"yamlText": YAML, "sourceName": "config_qualtrics_sleep.yaml"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["account"]["dataCenter"] == "yul1"
    assert r.json()["tokenFound"] is False
