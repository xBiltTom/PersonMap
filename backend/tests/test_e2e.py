import pytest
from app.core.database import async_session_maker
from app.engine.orchestrator import orchestrator
from app.models.investigation import Investigation
from app.models.target import Target


@pytest.mark.asyncio
async def test_end_to_end_investigation_rule_based():
    async with async_session_maker() as db:
        # Create test student target
        target = Target(
            full_name="Carlos Eduardo Mendoza",
            email="test_student_osint@gmail.com",
            username="testuser_osint_ci",
            phone="987654321",
            dni="74839201",
            university="Universidad Nacional de Tumbes",
            description="Estudiante de ingeniería de sistemas y seguridad",
        )
        db.add(target)
        await db.flush()

        investigation = Investigation(
            target_id=target.id,
            strategy="rule_based",
            status="pending",
        )
        db.add(investigation)
        await db.commit()
        inv_id = investigation.id

    # Run orchestrator
    await orchestrator.run_investigation(inv_id)

    # Verify results in DB
    async with async_session_maker() as db:
        inv = await db.get(Investigation, inv_id)
        assert inv is not None
        assert inv.status == "completed"
        assert inv.risk_score > 0
        assert inv.metrics is not None
        assert "execution_time_seconds" in inv.metrics
        print(f"\n[E2E Success] Completed in {inv.metrics['execution_time_seconds']}s with score {inv.risk_score}/100")
