#!/usr/bin/env python3
"""Provider-free Fair → review → Exposure → reconstruction → Graph V2 → cleanup."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.engine import make_url


def require_lite(database_url: str, environment: str):
    if environment != 'lite' or make_url(database_url).database != 'personmap_lite':
        raise RuntimeError('Smoke reconstruction exige PERSONMAP_ENV=lite y DATABASE_URL → personmap_lite.')


async def run_smoke(output: str | None = None):
    require_lite(os.getenv('DATABASE_URL', ''), os.getenv('PERSONMAP_ENV', ''))
    import httpx
    from sqlalchemy import delete, select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.core.config import settings
    from app.core.database import engine, get_db
    from app.main import app
    from app.models.entity import Entity
    from app.models.exposure_run import ExposureContentCache
    from app.models.reconstruction_run import ReconstructionRun
    from app.models.investigation import Investigation
    from app.models.target import Target
    from app.models.relationship import Relationship
    from app.schemas.target import TargetCreate
    from app.schemas.review import ReviewedFootprintDataset
    from app.services.exposure_lens import _is_attributed, _units, _unit_hash

    require_lite(settings.database_url, settings.personmap_env)
    settings.exposure_ai_enabled = False
    settings.reconstruction_ai_enabled = False
    async with engine.connect() as connection:
        assert (await connection.execute(text('SELECT current_database()'))).scalar_one() == 'personmap_lite'
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tag = 'reconstruction_' + uuid4().hex[:12]
    email = tag + '@example.org'
    target = Target(**TargetCreate(input_version=2, given_names='Fixture', family_names='Reconstruccion',
        emails=[email], usernames=[{'username': tag, 'platform': 'instagram'}]).persistence_values())
    target.extra_data['subject_consent'] = True
    investigation = Investigation(target=target, strategy='rule_based', status='completed',
        completed_at=datetime.now(timezone.utc), metrics={'acquisition_mode': 'fair',
        'fair_snapshot': {'execution': {'partial': False}, 'sources': {}}})
    target_id = None
    investigation_id = None
    hashes = set()
    original_cache_ids = set()
    async def database_dependency():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database_dependency
    try:
        async with factory() as db:
            db.add(investigation)
            await db.flush()
            target_id, investigation_id = target.id, investigation.id
            def entity(platform, kind='social_account', *, value=None, bio='', content=None, username=None):
                return Entity(investigation_id=investigation_id, entity_type=kind, platform=platform,
                    value=value or f'https://example.org/{platform}/{tag}', source_tool='controlled_fixture',
                    display_name='Fixture Reconstruccion', metadata_info={
                        'username': username or tag, 'bio': bio, 'public_content': content or [],
                        'source_tool': 'controlled_fixture', 'provenance': {'origin': 'automatic', 'status': 'discovered',
                            'subject_asserted': False, 'evidence_urls': []},
                        'evidence_urls': [f'https://example.org/{platform}/{tag}']})
            instagram = entity('instagram', value=f'https://www.instagram.com/{tag}/', bio=f'Contacto {email}')
            tiktok = entity('tiktok', value=f'https://www.tiktok.com/@{tag}', bio=f'Contacto {email}', content=[
                {'id': tag + '-post-1', 'authorship_role': 'coauthor', 'url': f'https://example.org/{tag}/post/1', 'text':
                    f'Tengo lupus y estudio en Universidad X. Contacto {email}.', 'posted_at': '2026-10-01T08:10:00Z'},
                {'id': tag + '-post-2', 'url': f'https://example.org/{tag}/post/2', 'text':
                    'Nos vemos en Calle Olivos 123. Todos los martes a las 08:10. Soy adventista y trabajo en Empresa Y.',
                    'posted_at': '2026-10-02T08:10:00Z'}])
            rejected = entity('youtube', value=f'https://www.youtube.com/@{tag}', bio='rejected-secret@example.net')
            uncertain = entity('github', value=f'https://github.com/{tag}', bio='uncertain-secret@example.net')
            academic = entity('openalex_author', 'academic', value='https://openalex.org/' + tag)
            paper = entity('research_paper', 'academic', value='Documento académico Universidad X', bio=f'Contacto {email}')
            breach = Entity(investigation_id=investigation_id, entity_type='breach', platform='data_leak',
                value=email, source_tool='controlled_fixture', metadata_info={'email': email, 'breaches': ['Fixture Leak']})
            stealer = Entity(investigation_id=investigation_id, entity_type='infostealer', platform='hudson_rock',
                value='fixture-infostealer:' + tag, source_tool='controlled_fixture', metadata_info={
                    'queried_by': 'email', 'email': email, 'computer_name': 'PRIVATE_MACHINE',
                    'malware_path': 'PRIVATE_PATH', 'ip': '192.0.2.15'})
            db.add_all([instagram, tiktok, rejected, uncertain, academic, paper, breach, stealer])
            await db.flush()
            db.add(Relationship(investigation_id=investigation_id, source_entity_id=academic.id,
                target_entity_id=paper.id, relation_type='authored_work', supports_group=False,
                evidence={'source': 'controlled_fixture', 'coauthors': ['Coauthor excluded']}))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://reconstruction-lite-smoke') as client:
            prefix = f'/api/v1/investigations/{investigation_id}'
            for item, decision in [(tiktok, 'confirmed'), (academic, 'confirmed'), (rejected, 'rejected'), (uncertain, 'uncertain')]:
                response = await client.patch(prefix + '/review/' + str(item.id), json={'decision': decision})
                assert response.status_code == 200, response.text
            response = await client.post(prefix + '/review/finalize')
            assert response.status_code == 200, response.text
            dataset = ReviewedFootprintDataset.model_validate((await client.get(prefix + '/reviewed-footprint')).json())
            hashes = {_unit_hash(u) for u in _units(dataset, [a for a in dataset.accounts if _is_attributed(a)])}
            async with factory() as db:
                original_cache_ids = set((await db.scalars(select(ExposureContentCache.id).where(
                    ExposureContentCache.content_hash.in_(hashes)))).all())
            response = await client.post(prefix + '/exposure/analyze')
            assert response.status_code == 200 and response.json()['status'] == 'completed', response.text
            response = await client.post(prefix + '/reconstruction/build')
            assert response.status_code == 200, response.text
            result = response.json()
            snapshot = result['snapshot']
            nodes = {n['id']: n for n in snapshot['graph']['nodes']}
            edges = snapshot['graph']['edges']
            assert sum(n['kind'] == 'subject' for n in nodes.values()) == 1
            assert sum(n['kind'] == 'alias' for n in nodes.values()) == 1
            assert sum(n['kind'] == 'account' for n in nodes.values()) == 2
            assert sum(n['kind'] == 'post' for n in nodes.values()) == 2
            assert any(e['type'] == 'SAME_ALIAS' for e in edges)
            assert any(e['type'] == 'COAUTHORED' and nodes[e['source']]['kind'] == 'account' for e in edges)
            assert any(e['type'] == 'SAME_EMAIL' for e in edges)
            assert any(e['type'] == 'AUTHORED' and nodes[e['source']]['kind'] == 'academic_profile' for e in edges)
            assert any(e['type'] == 'EXPOSED_IN_BREACH' and nodes[e['source']]['kind'] == 'email' for e in edges)
            assert any(e['type'] == 'EXPOSED_IN_INFOSTEALER' and nodes[e['source']]['kind'] == 'email' for e in edges)
            assert any(e['type'] == 'HAS_EXPOSURE_SIGNAL' and e['evidence_refs'] for e in edges)
            assert all(e['source'] in nodes and e['target'] in nodes for e in edges)
            serialized = json.dumps(result)
            for forbidden in ('lupus', 'adventista', 'Olivos 123', '08:10', 'martes', str(rejected.id), str(uncertain.id), 'Coauthor excluded', 'PRIVATE_MACHINE', 'PRIVATE_PATH', '192.0.2.15'):
                assert forbidden not in serialized, forbidden
            assert 'Universidad X' in serialized and 'Empresa Y' in serialized
            async with factory() as db:
                persisted = (await db.scalars(select(ReconstructionRun).where(ReconstructionRun.investigation_id == investigation_id))).one()
                assert persisted.snapshot == snapshot
            assert (await client.post(prefix + '/reconstruction/build')).json()['cache_hit'] is True
            assert (await client.get(prefix + '/reconstruction')).json()['snapshot'] == snapshot
            if output:
                Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(f'SMOKE OK: Lite Fair → Verification → Exposure → Reconstruction/Graph V2; {len(nodes)} nodes, {len(edges)} explained edges; safety/persistence/cache checked.')
    finally:
        app.dependency_overrides.pop(get_db, None)
        if target_id:
            async with factory() as db:
                await db.execute(delete(Target).where(Target.id == target_id))
                if hashes:
                    await db.execute(delete(ExposureContentCache).where(ExposureContentCache.content_hash.in_(hashes),
                        ExposureContentCache.id.not_in(original_cache_ids)))
                await db.commit()
                assert not (await db.scalars(select(ReconstructionRun).where(ReconstructionRun.investigation_id == investigation_id))).all()
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', help='Optional path for the safe synthetic report JSON.')
    args = parser.parse_args()
    asyncio.run(run_smoke(args.output))
