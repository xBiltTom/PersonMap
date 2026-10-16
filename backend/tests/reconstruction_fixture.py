from datetime import datetime, timezone
from uuid import UUID

from app.schemas.review import ReviewedFootprintDataset
from app.schemas.exposure import ExposureReport
from app.schemas.footprint import DataProvenance
from app.services.exposure_lens import dataset_hash

IDS = {name: str(UUID(int=i + 1)) for i, name in enumerate(['instagram', 'tiktok', 'academic', 'paper', 'breach', 'rejected', 'uncertain', 'pending'])}
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)
RAW = 'Tengo lupus y soy adventista. Calle Olivos 123. Todos los martes a las 08:10. Universidad X.'


def fixture_dataset(posts=2):
    declared = DataProvenance(origin='subject', status='declared').model_dump()
    confirmed = DataProvenance(origin='automatic', status='confirmed').model_dump()
    def account(name, status='confirmed'):
        return dict(entity_id=IDS[name], entity_type='social_account', platform=name,
                    username='shared', display_name=RAW, bio=RAW, value='https://example.org/' + name,
                    profile_url='https://example.org/' + name, source_tools=['Apify', 'SearchDorker'],
                    ownership={'status': 'subject_confirmed' if status == 'confirmed' else status},
                    provenance={**confirmed, 'status': status})
    return ReviewedFootprintDataset.model_validate(dict(
        subject={'declared': [dict(seed_id='seed-' + kind, kind=kind, value=value, provenance=declared)
            for kind, value in [('name', 'Ana Perez'), ('email', 'public@example.org'),
                                ('username', 'shared'), ('phone', '+51912345678')]]},
        accounts=[account('instagram'), account('tiktok'), account('rejected', 'rejected'),
                  account('uncertain', 'uncertain'), {**account('pending', 'discovered'), 'ownership': {}}],
        emails=[dict(entity_type='email', value='public@example.org', provenance=declared,
                     ownership={'status': 'subject_declared'})],
        academic_profiles=[dict(entity_id=IDS['academic'], entity_type='academic_profile', platform='openalex_author',
            value='https://openalex.org/A1', profile_url='https://openalex.org/A1', display_name=RAW, bio=RAW,
            provenance=confirmed, ownership={'status': 'subject_confirmed'})],
        documents=[dict(entity_id=IDS['paper'], entity_type='academic_publication', value=RAW, bio=RAW,
            display_name=RAW, evidence_urls=['https://example.org/paper.pdf'], provenance=confirmed,
            associated_profile_entity_id=IDS['academic'], authorship_evidence={'relation': 'authored_work', 'coauthors': ['Coauthor Secret']})],
        breaches=[dict(entity_id=IDS['breach'], email='public@example.org', breaches=['Fixture Leak'], provenance=confirmed)],
        social_content=[dict(id=f'post-{i}', account_entity_id=IDS['instagram' if i % 2 == 0 else 'tiktok'],
            text=RAW, caption=RAW, url=f'https://example.org/posts/{i}', posted_at='2026-10-01T08:10:00Z') for i in range(posts)],
        review={}, execution={'acquisition_partial': False},
    ))


def fixture_exposure(dataset):
    evidence = [dict(source_type='entity', source_id=IDS[p], platform=p,
                     url='https://example.org/' + p, excerpt='Correo público visible: public@example.org')
                for p in ('instagram', 'tiktok')]
    return ExposureReport.model_validate(dict(investigation_id='fixture', dataset_hash=dataset_hash(dataset),
        status='completed', generated_at=NOW, findings=[
            dict(id='email', category='contact_exposure', severity='medium', title='Correo público',
                 summary='Correo visible', why_it_matters='Contacto público', evidence=evidence),
            dict(id='education', category='education_work_context', severity='medium', title='Estudio',
                 summary='Contexto institucional', why_it_matters='Contexto público', evidence=[{
                     **evidence[0], 'excerpt': 'Contexto educativo observado: Universidad X.'}]),
            dict(id='location', category='location_disclosure', severity='high', title='Ubicación',
                 summary='Referencia generalizada', why_it_matters='Privacidad', evidence=[{
                     **evidence[0], 'excerpt': 'Referencia de ubicación específica [redactada].'}]),
        ]))
