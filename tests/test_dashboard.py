from tests.conftest import login_as
from tests.test_workflow import build_impact


def test_every_feed_item_has_a_relevance_reason(client, conn, users):
    priya = users["Priya Menon"]
    build_impact(conn, priya["id"])
    login_as(client, priya["id"])
    response = client.get("/api/v1/dashboard?scope=me")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["feed"]
    assert all(item["relevance"]["reason"] and isinstance(item["relevance"]["weight"], int) for item in body["feed"])


def test_me_changes_ranking_not_access_and_differs_from_all(client, conn, users):
    priya, alex = users["Priya Menon"], users["Alex Tan"]
    mine = build_impact(conn, priya["id"])
    other = build_impact(conn, alex["id"])
    login_as(client, priya["id"])
    mine_feed = client.get("/api/v1/dashboard?scope=me").json()["feed"]
    all_feed = client.get("/api/v1/dashboard?scope=all").json()["feed"]
    assert {item["id"] for item in mine_feed} == {mine["impact"]}
    assert {item["id"] for item in all_feed} == {mine["impact"], other["impact"]}
    assert next(item for item in all_feed if item["id"] == other["impact"])["relevance"]["reason"]
