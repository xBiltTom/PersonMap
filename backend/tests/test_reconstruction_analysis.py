"""Behavior of per-post risk ranking and evidence attribution."""
from reconstruction_fixture import fixture_dataset, fixture_exposure, NOW
from app.reconstruction.builder import build_snapshot
from app.services.digital_reconstruction import reconstruction_config
from app.schemas.exposure import ExposureFinding


def build(dataset, exposure=None):
    exposure = exposure or fixture_exposure(dataset)
    return build_snapshot(dataset, exposure, investigation_id='fixture', data_hash='data',
        exposure_hash='exposure', input_hash='input', config=reconstruction_config(), generated_at=NOW)


def test_all_posts_ranked_with_traceable_minimized_evidence():
    dataset = fixture_dataset(30)
    for post in dataset.social_content:
        post['text'] = post['caption'] = 'Una publicación sin detalles personales.'
    dataset.social_content[25]['text'] = 'Mi dirección: Calle Olivos 123. Universidad Nacional.'
    dataset.social_content[26]['text'] = 'Contacto: public@example.org'
    result = build(dataset)
    assert len(result.post_assessments) == 30  # Not capped at Exposure's top 20.
    first = result.post_assessments[0]
    facts = {fact.id: fact for fact in result.facts}
    assert facts[first.fact_id].url.endswith('/25')
    assert first.severity == 'high'
    assert first.recommendations
    assert any('específica' in signal.observation for signal in first.signals)
    assert all(ref in result.evidence for item in result.post_assessments for signal in item.signals for ref in signal.evidence_refs)
    assert 'Calle Olivos' not in result.model_dump_json()
    assert any(signal.category == 'contact_exposure' for item in result.post_assessments for signal in item.signals)
    assert all(key in facts for claim in result.identity_portrait for key in claim.fact_ids)


def test_missing_text_and_no_signals_are_different():
    dataset = fixture_dataset()
    dataset.social_content[0]['text'] = dataset.social_content[0]['caption'] = ''
    dataset.social_content[1]['text'] = dataset.social_content[1]['caption'] = 'Hola mundo'
    result = build(dataset)
    assert {item.status for item in result.post_assessments} == {'no_text', 'no_signals'}
    assert all(item.severity is None for item in result.post_assessments)


def test_duplicate_external_ids_never_transfer_ai_signals_between_accounts():
    dataset = fixture_dataset()
    for post in dataset.social_content:
        post['id'] = 'same-id'
        post['text'] = post['caption'] = 'Hola mundo'
    exposure = fixture_exposure(dataset)
    exposure.findings.append(ExposureFinding(id='ai', category='biographical_identifiers', severity='medium',
        title='Dato público', summary='Dato', why_it_matters='Contexto', analysis_method='ai',
        evidence=[dict(source_type='content', source_id='same-id', platform='instagram',
            url=dataset.social_content[0]['url'], excerpt='Un identificador biográfico público.')]))
    result = build(dataset, exposure)
    assessed = [item for item in result.post_assessments if item.signals]
    assert len(assessed) == 1
    assert next(fact for fact in result.facts if fact.id == assessed[0].fact_id).platform == 'instagram'
    assert assessed[0].signals[0].analysis_method == 'ai'


def test_unknown_source_and_inferred_findings_do_not_create_post_risk():
    dataset = fixture_dataset()
    for post in dataset.social_content:
        post['text'] = post['caption'] = 'Hola mundo'
    exposure = fixture_exposure(dataset)
    for index, basis in enumerate(['observed', 'inferred']):
        exposure.findings.append(ExposureFinding(id=f'ignored-{index}', category='location_disclosure',
            severity='high', title='Ubicación', summary='Lugar', why_it_matters='Contexto', basis=basis,
            evidence=[dict(source_type='content', source_id='unknown' if basis == 'observed' else 'post-0',
                url='https://example.org/unknown' if basis == 'observed' else dataset.social_content[0]['url'])]))
    assert all(item.status == 'no_signals' for item in build(dataset, exposure).post_assessments)
