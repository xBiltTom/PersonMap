"""Context-sensitive risk calibration and literal evidence grounding."""
import pytest

from reconstruction_fixture import fixture_dataset
from test_reconstruction_analysis import build
from app.core.config import settings
from app.reconstruction import semantic


def enable(monkeypatch):
    monkeypatch.setattr(settings, 'reconstruction_ai_enabled', True)
    monkeypatch.setattr(settings, 'llm_model', 'fixture/model')
    monkeypatch.setattr(settings, 'llm_api_key', 'fixture-key')


def reading(fact_id, quote, severity='low'):
    return semantic.PostReading(fact_id=fact_id, title='Anuncio de comunidad universitaria',
        context='La publicación colaborativa presenta una comunidad universitaria y su carrera.', severity=severity,
        explanation='El anuncio añade contexto académico público; su propósito es difundir la comunidad y no revela una ubicación personal actual.',
        signals=[dict(category='education_work_context', quote=quote,
            observation='El texto menciona explícitamente a la Universidad Nacional.',
            why_it_matters='Esta referencia facilita relacionar la cuenta colaboradora con una comunidad académica, sin demostrar matrícula.')],
        recommendations=['Revisa si deseas mantener visible la colaboración entre el perfil personal y la comunidad.'],
        limitations=['La colaboración no acredita matrícula, asistencia ni ciclo académico actual.'])


@pytest.mark.asyncio
async def test_semantic_reading_replaces_keyword_false_positives_with_verified_quotes(monkeypatch):
    enable(monkeypatch)
    dataset = fixture_dataset(1)
    dataset.social_content[0].update(text='Nuestro viaje como comunidad de la Universidad Nacional.', caption='', authorship_role='coauthor')
    snapshot = build(dataset)
    fact_id = snapshot.post_assessments[0].fact_id

    async def complete(prompt, payload, schema, max_tokens):
        if schema is semantic.Readings:
            assert payload['posts'][0]['authorship_role'] == 'coauthor'
            assert 'no son desplazamientos' in prompt
            return semantic.Readings(posts=[reading(fact_id, 'Universidad Nacional')])
        return semantic.Portrait(insights=[dict(text='La cuenta colaboró en una publicación que menciona a la Universidad Nacional.',
            basis='OBSERVED', caveat='No acredita matrícula ni pertenencia actual.',
            citations=[dict(fact_id=fact_id, quote='Universidad Nacional')])])

    monkeypatch.setattr(semantic, 'complete', complete)
    result = await semantic.analyze_snapshot(snapshot, dataset)
    post = result.post_assessments[0]
    assert post.severity == 'low'
    assert post.analysis_method == 'ai'
    assert {signal.category for signal in post.signals} == {'education_work_context'}
    assert result.content_analysis_status == 'completed'
    assert result.identity_portrait[0].basis == 'OBSERVED'
    assert result.identity_portrait[0].caveat
    assert result.evidence[post.signals[0].evidence_refs[0]].excerpt == 'Universidad Nacional'


@pytest.mark.asyncio
async def test_invented_quotes_keep_local_fallback(monkeypatch):
    enable(monkeypatch)
    dataset = fixture_dataset(1)
    snapshot = build(dataset)
    old = snapshot.post_assessments[0].model_copy(deep=True)

    async def complete(prompt, payload, schema, max_tokens):
        return semantic.Readings(posts=[reading(old.fact_id, 'Instituto Inventado')])

    monkeypatch.setattr(semantic, 'complete', complete)
    result = await semantic.analyze_snapshot(snapshot, dataset)
    assert result.content_analysis_status == 'fallback'
    assert result.post_assessments[0] == old


@pytest.mark.asyncio
async def test_model_cannot_dismiss_explicit_precise_location(monkeypatch):
    enable(monkeypatch)
    dataset = fixture_dataset(1)
    dataset.social_content[0].update(text='Calle Olivos 123. Universidad Nacional.', caption='')
    snapshot = build(dataset)
    fact_id = snapshot.post_assessments[0].fact_id

    async def complete(prompt, payload, schema, max_tokens):
        if schema is semantic.Readings:
            assert 'Calle Olivos' not in payload['posts'][0]['text']
            return semantic.Readings(posts=[reading(fact_id, 'Universidad Nacional', 'informational')])
        raise RuntimeError('provider unavailable')

    monkeypatch.setattr(semantic, 'complete', complete)
    result = await semantic.analyze_snapshot(snapshot, dataset)
    assert result.post_assessments[0].severity == 'high'
    assert any(signal.category == 'location_disclosure' for signal in result.post_assessments[0].signals)
    assert 'Calle Olivos' not in result.model_dump_json()


@pytest.mark.asyncio
async def test_cross_source_identity_requires_more_than_one_source(monkeypatch):
    enable(monkeypatch)
    dataset = fixture_dataset(1)
    dataset.social_content[0].update(text='Universidad Nacional', caption='')
    snapshot = build(dataset)
    fact_id = snapshot.post_assessments[0].fact_id

    async def complete(prompt, payload, schema, max_tokens):
        if schema is semantic.Readings:
            return semantic.Readings(posts=[reading(fact_id, 'Universidad Nacional')])
        return semantic.Portrait(insights=[dict(text='Dos fuentes conectan esta cuenta con la misma universidad.',
            basis='CORRELATED', caveat='La relación no demuestra matrícula actual.',
            citations=[dict(fact_id=fact_id, quote='Universidad Nacional')])])

    monkeypatch.setattr(semantic, 'complete', complete)
    result = await semantic.analyze_snapshot(snapshot, dataset)
    assert all('Dos fuentes' not in claim.text for claim in result.identity_portrait)


def test_publication_dates_do_not_fail_as_phone_numbers():
    assert semantic.safe_prose('El anuncio fue publicado el 2024-09-20 y es histórico.', {'2024-09-20'})
    assert not semantic.safe_prose('Contacta al +51912345678 para participar.', {'2024-09-20'})
    assert not semantic.grounded('[hora omitida]', 'Se anunció a las [hora omitida].')
    assert semantic.clean_source('Director\u200b de TI') == 'Director de TI'
    assert semantic.safe_prose('Revisa las políticas de privacidad.', set())


def test_connected_portrait_uses_multiple_actual_publications():
    dataset = fixture_dataset(2)
    result = build(dataset)
    for item in result.post_assessments:
        item.analysis_method = 'ai'
        item.signals = []
        fact = next(fact for fact in result.facts if fact.id == item.fact_id)
        # Both posts must refer to the same reviewed account for this connection.
        fact.source_entity_ids = ['same-reviewed-account']
        quote = 'Promoción 28 de Ingeniería de Sistemas'
        ref = semantic.add_evidence(result, fact, quote)
        from app.schemas.reconstruction import PostRiskSignal
        item.signals.append(PostRiskSignal(category='education_work_context', label='estudio o trabajo',
            severity='low', observation=quote, why_it_matters='Contexto académico explícito.',
            recommendations=[], evidence_refs=[ref]))
    claims = semantic.connected_portrait(result)
    academic = next(claim for claim in claims if 'contexto académico' in claim.text)
    assert len(academic.fact_ids) == 2
    assert len(academic.evidence_refs) == 2
    assert academic.basis == 'CORRELATED'
    assert 'No acredita matrícula' in academic.caveat
