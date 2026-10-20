import asyncio
import uuid
import httpx

BASE_URL = "http://localhost:8000/api"

async def run_simulation():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        print("\n=== NEWTONITE AUTOMATED CONDITION SIMULATOR ===\n")

        # 1. Fetch seeded users and teams
        users = (await client.get("/users")).json()
        teams = (await client.get("/teams")).json()

        # Select target team with both a LEAD and a MEMBER
        target_team = next(
            (t for t in teams if any(m["role"] == "LEAD" for m in t.get("memberships", [])) and any(m["role"] == "MEMBER" for m in t.get("memberships", []))),
            teams[0]
        )
        team_id = target_team["id"]
        memberships = target_team.get("memberships", [])

        # Identify roles for target_team
        lead_membership = next(m for m in memberships if m["role"] == "LEAD")
        lead_user = lead_membership.get("user") or next(u for u in users if u["id"] == lead_membership["user_id"])

        member_membership = next(m for m in memberships if m["role"] == "MEMBER")
        member_user = member_membership.get("user") or next(u for u in users if u["id"] == member_membership["user_id"])

        team_user_ids = {m["user_id"] for m in memberships}
        outsider_user = next(u for u in users if u["id"] not in team_user_ids)

        print(f"Target Team: {target_team['name']}")
        print(f"  - Lead User:     {lead_user['full_name']} (Role: LEAD)")
        print(f"  - Member User:   {member_user['full_name']} (Role: MEMBER)")
        print(f"  - Outsider User: {outsider_user['full_name']} (Not in team)\n")

        # CONDITION 1: Idempotency (Duplicate Request Prevention)
        idem_key = f"sim-idem-{uuid.uuid4()}"
        payload = {
            "title": "Simulated High-Priority Payment Gateway Outage",
            "description": "Automated simulation of duplicate submission under network lag",
            "category": "PAYMENT_INVESTIGATION",
            "priority": "CRITICAL",
            "team_id": team_id,
            "requires_approval": True,
            "next_action_required": "Claim and investigate gateway logs"
        }
        r1, r2 = await asyncio.gather(
            client.post("/work-items", headers={"X-User-Id": member_user["id"], "Idempotency-Key": idem_key}, json=payload),
            client.post("/work-items", headers={"X-User-Id": member_user["id"], "Idempotency-Key": idem_key}, json=payload),
        )
        item = r1.json()
        item_id = item["id"]
        assert r1.json()["id"] == r2.json()["id"], "Idempotency failed!"
        print(f"[PASS] 1. Idempotency Guard: Duplicate POST returned identical WorkItem ID ({item_id[:8]}...)")

        # CONDITION 2: Simultaneous Claim Race Condition
        c1, c2 = await asyncio.gather(
            client.post(f"/work-items/{item_id}/claim", headers={"X-User-Id": lead_user["id"], "Idempotency-Key": str(uuid.uuid4())}, json={"expected_version": 1}),
            client.post(f"/work-items/{item_id}/claim", headers={"X-User-Id": member_user["id"], "Idempotency-Key": str(uuid.uuid4())}, json={"expected_version": 1}),
        )
        statuses = sorted([c1.status_code, c2.status_code])
        assert statuses == [200, 409], f"Expected [200, 409], got {statuses}"
        print(f"[PASS] 2. Simultaneous Claim Race: 1 Winner (200 OK) & 1 Conflict Rejected (409 Conflict)")

        # CONDITION 3: Stale Version Update Prevention
        stale_res = await client.post(
            f"/work-items/{item_id}/transition",
            headers={"X-User-Id": member_user["id"], "Idempotency-Key": str(uuid.uuid4())},
            json={"target_status": "BLOCKED", "next_action_required": "Wait", "reason": "Stale attempt", "expected_version": 1}
        )
        assert stale_res.status_code == 409
        print(f"[PASS] 3. Stale Edit Protection: Rejected v1 mutation when server was at v2 (409 Conflict)")

        # CONDITION 4: Cross-Team Authorization Enforcement
        unauth_res = await client.post(
            f"/work-items/{item_id}/transition",
            headers={"X-User-Id": outsider_user["id"], "Idempotency-Key": str(uuid.uuid4())},
            json={"target_status": "BLOCKED", "next_action_required": "Hack", "reason": "Cross-team", "expected_version": 2}
        )
        assert unauth_res.status_code == 403
        print(f"[PASS] 4. Cross-Team RBAC: Blocked user outside owning team (403 Forbidden)")

        # CONDITION 5: Workflow State Machine & Approval Gate Enforcement
        bypass_res = await client.post(
            f"/work-items/{item_id}/transition",
            headers={"X-User-Id": lead_user["id"], "Idempotency-Key": str(uuid.uuid4())},
            json={"target_status": "RESOLVED", "next_action_required": "Done", "reason": "Skip approval", "expected_version": 2}
        )
        assert bypass_res.status_code == 422
        print(f"[PASS] 5. Approval Gate Rule: Blocked direct IN_PROGRESS -> RESOLVED without approval (422)")

        print("\n=== ALL SIMULATED CONDITIONS VERIFIED SUCCESSFULLY ===\n")

if __name__ == "__main__":
    asyncio.run(run_simulation())