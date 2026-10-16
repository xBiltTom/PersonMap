import json

import pytest

from reconstruction_fixture import fixture_dataset, fixture_exposure, IDS, NOW
from app.reconstruction.builder import build_snapshot
from app.reconstruction.safety import safe_day
from app.services.digital_reconstruction import reconstruction_config, exposure_fingerprint, input_fingerprint


def snapshot(dataset=None, config=None):
    dataset = dataset or fixture_dataset()
    exposure = fixture_exposure(dataset)
    config = config or reconstruction_config()
    digest = exposure_fingerprint(exposure)
    return build_snapshot(dataset, exposure, investigation_id='fixture', data_hash=exposure.dataset_hash,
                          exposure_hash=digest, input_hash=input_fingerprint(exposure.dataset_hash, digest, config),
                          config=config, generated_at=NOW)


def test_declared_accounts_public_identifiers_and_epistemology():
    result = snapshot()
    assert len(result.identity.accounts) == 2
    assert len([f for f in result.facts if f.kind == 'alias']) == 1
    assert all(f.basis == 'DECLARED' for f in result.facts if f.id in result.identity.declared)
    assert {'name', 'email', 'phone', 'alias'} <= {f.kind for f in result.facts if f.id in result.identity.declared}
    assert any(f.kind == 'email' for f in result.facts if f.id in result.identity.public_identifiers)
    assert not any(f.basis == 'INFERRED' for f in result.facts)
    for excluded in ('rejected', 'uncertain', 'pending'):
        assert IDS[excluded] not in result.model_dump_json()


def test_explainable_alias_email_breach_academic_and_post_edges():
    result = snapshot()
    nodes = {f.id: f for f in result.facts}
    relations = result.correlations
    assert len([e for e in relations if e.type == 'SAME_ALIAS']) == 1
    assert len([e for e in relations if e.type == 'SAME_EMAIL']) == 1
    for edge in relations:
        assert edge.evidence_refs and edge.evidence_count > 0
        assert edge.source in nodes and edge.target in nodes
        assert all(ref in result.evidence for ref in edge.evidence_refs)
        if edge.type == 'EXPOSED_IN_BREACH':
            assert nodes[edge.source].kind == 'email' and nodes[edge.target].kind == 'breach'
        if edge.type == 'AUTHORED':
            assert nodes[edge.source].kind == 'academic_profile' and nodes[edge.target].kind == 'publication'
        if edge.type == 'PUBLISHED':
            assert nodes[edge.source].kind == 'account' and nodes[edge.target].kind == 'post'
        if edge.type.startswith('SAME_'):
            assert edge.basis == 'CORRELATED'
    assert {'AUTHORED', 'PUBLISHED', 'EXPOSED_IN_BREACH', 'HAS_EXPOSURE_SIGNAL'} <= {e.type for e in relations}


def test_safety_timeline_and_exposure_is_separate():
    result = snapshot()
    serialized = result.model_dump_json().lower()
    for forbidden in ('lupus', 'adventista', 'calle olivos', '08:10', 'martes', 'coauthor secret', 'probability', 'confidence'):
        assert forbidden not in serialized
    assert 'Universidad X' in result.model_dump_json()
    assert len(result.timeline) == 2
    assert all(item.date == '2026-10-01' for item in result.timeline)
    assert all(f.severity is None for f in result.facts if f.kind != 'exposure')
    assert all(claim.fact_ids for claim in result.summary)
    assert all(key in {f.id for f in result.facts} for claim in result.summary for key in claim.fact_ids)


def test_stable_ids_order_and_graph_determinism():
    dataset = fixture_dataset()
    first = snapshot(dataset)
    dataset.accounts.reverse()
    dataset.social_content.reverse()
    dataset.subject['declared'].reverse()
    second = snapshot(dataset)
    assert first.graph == second.graph
    assert first.facts == second.facts
    assert first.summary == second.summary
    assert first.timeline == second.timeline


def test_graph_caps_large_dataset_has_no_dangling_edges_and_preserves_parents():
    config = reconstruction_config() | {'graph_max_total_nodes': 25, 'graph_max_post_nodes': 5,
                                       'graph_max_document_nodes': 0, 'graph_max_exposure_nodes': 2}
    result = snapshot(fixture_dataset(500), config)
    nodes = {n.id: n for n in result.graph.nodes}
    assert len(nodes) <= 25
    assert sum(n.kind == 'post' for n in nodes.values()) <= 5
    assert sum(n.kind == 'exposure' for n in nodes.values()) <= 2
    assert not any(n.kind in {'document', 'publication'} for n in nodes.values())
    assert result.graph.omitted_nodes > 400
    assert len(result.timeline) <= 50
    assert result.counts['post'] == 500
    assert sum(result.content_by_platform.values()) == 500
    assert all(e.source in nodes and e.target in nodes for e in result.graph.edges)
    for n in nodes.values():
        if n.kind in {'post', 'publication', 'breach'}:
            assert any(e.target == n.id and e.type in {'PUBLISHED', 'AUTHORED', 'EXPOSED_IN_BREACH'} for e in result.graph.edges)
        if n.kind == 'exposure':
            assert any(e.target == n.id and e.type == 'HAS_EXPOSURE_SIGNAL' for e in result.graph.edges)


@pytest.mark.parametrize('value', ['martes', '08:10', '2026-99-99', '2026-10-01 at 08:10'])
def test_non_date_timeline_values_are_rejected(value):
    assert safe_day(value) is None


def test_partial_coverage_and_exposure_hash_changes():
    dataset = fixture_dataset()
    exposure = fixture_exposure(dataset)
    first = exposure_fingerprint(exposure)
    exposure.cache_hit = True
    assert exposure_fingerprint(exposure) == first
    exposure.summary.medium += 1
    assert exposure_fingerprint(exposure) != first
    dataset.execution['acquisition_partial'] = True
    assert snapshot(dataset).coverage == 'partial'
    config = reconstruction_config()
    assert input_fingerprint('dataset', 'exposure', config) != input_fingerprint('dataset', 'new-exposure', config)


@pytest.mark.parametrize(('url', 'environment'), [
    ('postgresql+asyncpg://postgres@localhost/person_map', 'lite'),
    ('postgresql+asyncpg://postgres@localhost/another_database', 'lite'),
    ('postgresql+asyncpg://postgres@localhost/personmap_lite', 'development'),
])
def test_smoke_refuses_legacy_or_non_lite_database(url, environment):
    from scripts.smoke_reconstruction import require_lite
    with pytest.raises(RuntimeError, match='personmap_lite'):
        require_lite(url, environment)


def test_duplicate_canonical_entities_do_not_duplicate_graph_nodes():
    dataset = fixture_dataset()
    dataset.accounts.extend(dataset.accounts[:2])
    dataset.documents.extend(dataset.documents)
    result = snapshot(dataset)
    assert result.counts['account'] == 2
    assert result.counts['publication'] == 1
    assert len({node.id for node in result.graph.nodes}) == len(result.graph.nodes)


def test_no_raw_text_is_used_for_content_ids_or_evidence():
    dataset = fixture_dataset()
    dataset.social_content[0].pop('id')
    dataset.social_content[0].pop('url')
    result = snapshot(dataset)
    assert result.counts['post'] == 1
    assert 'lupus' not in result.model_dump_json()


@pytest.mark.parametrize('url', [
    'https://example.org/Calle%20X%20123', 'https://example.org/post/08%3A10',
    'https://example.org/post/08%253A10', 'https://example.org/every%20Tuesday%20at%208',
])
def test_operational_urls_are_not_reintroduced(url):
    from app.reconstruction.safety import safe_url
    assert safe_url(url) is None


def test_external_content_ids_never_reproduce_raw_text():
    dataset = fixture_dataset()
    dataset.social_content[0]['id'] = 'Tengo lupus y Calle Olivos 123 a las 08:10'
    assert 'lupus' not in snapshot(dataset).model_dump_json()


@pytest.mark.parametrize(('url', 'expected_kind'), [
    ('https://github.com/shared/project', 'repository'),
    ('https://github.com/another/project', 'post'),
    ('https://github.com/shared', 'post'),
])
def test_only_explicit_repository_under_attributed_owner_is_a_repository(url, expected_kind):
    dataset = fixture_dataset()
    dataset.accounts[0].platform = 'github'
    dataset.social_content[0]['content_type'] = 'repository'
    dataset.social_content[0]['url'] = url
    result = snapshot(dataset)
    fact = next(f for f in result.facts if f.url == url and f.kind in {'post', 'repository'})
    assert fact.kind == expected_kind


def test_explicit_cross_link_does_not_change_ownership_basis():
    dataset = fixture_dataset()
    exposure = fixture_exposure(dataset)
    from app.schemas.exposure import ExposureFinding
    exposure.findings.append(ExposureFinding.model_validate(dict(
        id='cross-link', category='cross_platform_correlation', severity='medium', title='Enlace',
        summary='Enlace observado', why_it_matters='Correlación', signals=['enlace_explicito'],
        evidence=[dict(source_type='entity', source_id=IDS['instagram'], url='https://example.org/tiktok', excerpt='Enlace directo observado.')],
    )))
    result = build_snapshot(dataset, exposure, investigation_id='fixture', data_hash=exposure.dataset_hash,
        exposure_hash='exposure', input_hash='input', config=reconstruction_config(), generated_at=NOW)
    assert any(e.type == 'LINKS_TO' and e.source == 'entity:' + IDS['instagram'] and e.target == 'entity:' + IDS['tiktok']
               for e in result.correlations)
    assert all(f.ownership_basis == 'subject_confirmed' for f in result.facts if f.kind == 'account')



def test_seed_only_accounts_are_not_misrepresented_as_public_observations():
    dataset = fixture_dataset(0)
    dataset.accounts = dataset.accounts[:2]
    for index, account in enumerate(dataset.accounts):
        account.entity_id = None
        account.seed_id = f'seed-account-{index}'
        account.ownership = {'status': 'subject_declared'}
        account.provenance.origin = 'subject'
        account.provenance.status = 'declared'
    result = snapshot(dataset)
    assert result.counts['account'] == 2
    assert all(e.basis == 'DECLARED' for e in result.correlations if e.type == 'USES_ALIAS')
    assert not any(e.type == 'SAME_ALIAS' for e in result.correlations)



def test_inferred_exposure_is_not_promoted_to_an_observed_fact():
    dataset = fixture_dataset()
    exposure = fixture_exposure(dataset)
    exposure.findings[0].basis = 'inferred'
    result = build_snapshot(dataset, exposure, investigation_id='fixture', data_hash=exposure.dataset_hash,
        exposure_hash='exposure', input_hash='input', config=reconstruction_config(), generated_at=NOW)
    assert 'exposure:email' not in {fact.id for fact in result.facts}



def test_raw_post_and_bio_changes_cannot_change_reconstructed_graph():
    dataset = fixture_dataset()
    first = snapshot(dataset)
    for account in dataset.accounts:
        account.bio = 'Otro texto desconocido y sensible que no debe interpretarse'
    for post in dataset.social_content:
        post['text'] = 'Una nueva rutina a las 09:15 y una dirección distinta'
        post['caption'] = 'Otro párrafo sin valor para la reconstrucción'
    assert snapshot(dataset).graph == first.graph
