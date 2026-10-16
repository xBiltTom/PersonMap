from collections import Counter

from app.schemas.reconstruction import NarrativeClaim, TimelineItem
from app.reconstruction.registry import FactRegistry


def build_narrative(registry: FactRegistry):
    facts = sorted(registry.facts.values(), key=lambda f: f.id)
    accounts = [f for f in facts if f.kind == 'account']
    artifacts = [f for f in facts if f.kind in {'document', 'publication'}]
    exposures = [f for f in facts if f.kind == 'exposure']
    claims = [NarrativeClaim(text=f'La huella revisada contiene {len(accounts)} cuentas atribuidas y '
                            f'{len(artifacts)} documentos o publicaciones académicas.',
                            fact_ids=[f.id for f in accounts + artifacts] or [next(f.id for f in facts if f.kind == 'subject')])]
    aliases = [e for e in registry.relations.values() if e.type == 'SAME_ALIAS']
    emails = [e for e in registry.relations.values() if e.type == 'SAME_EMAIL']
    if aliases or emails:
        refs = sorted({v for e in aliases + emails for v in (e.source, e.target)})
        claims.append(NarrativeClaim(text=f'Se observaron {len(aliases)} relaciones de alias compartido y '
                                     f'{len(emails)} de correo público compartido entre fuentes atribuidas. '
                                     'Estas correlaciones no determinan ownership.', fact_ids=refs))
    if exposures:
        impact = sum(f.severity in {'high', 'medium'} for f in exposures)
        claims.append(NarrativeClaim(text=f'Exposure Lens identificó {len(exposures)} señales representadas; '
                                     f'{impact} tienen impacto potencial medio o alto. '
                                     'La severidad describe el hallazgo.', fact_ids=[f.id for f in exposures]))
    breaches = [f for f in facts if f.kind in {'breach', 'infostealer'}]
    if breaches:
        claims.append(NarrativeClaim(text=f'Hay {len(breaches)} registros de exposición en brechas o infostealers asociados a identificadores atribuidos. '
                                     'Una brecha no es prueba de identidad.', fact_ids=[f.id for f in breaches]))
    return claims


def build_timeline(registry: FactRegistry, maximum: int):
    return [TimelineItem(id='timeline:' + f.id, date=f.date, kind=f.kind, label=f.label,
                         platform=f.platform, fact_ids=[f.id], evidence_refs=f.evidence_refs)
            for f in sorted(registry.facts.values(), key=lambda f: (f.date or '', f.id), reverse=True)
            if f.date and f.kind in {'post', 'publication', 'document', 'repository'}][:maximum]


def content_counts(registry):
    return dict(sorted(Counter(f.platform or 'público' for f in registry.facts.values()
                               if f.kind in {'post', 'repository'}).items()))
