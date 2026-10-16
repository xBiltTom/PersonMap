"""Per-publication assessment using reviewed content and validated exposure signals."""
from collections import Counter

from app.exposure.detectors import exact_emails, exact_phones
from app.reconstruction.safety import minimized_evidence, safe_url
from app.schemas.reconstruction import NarrativeClaim, PostAssessment, PostRiskSignal
from app.services.exposure_lens import CATEGORY_LABELS, RECOMMENDATIONS, _local_signals

SEVERITY = {'high': 3, 'medium': 2, 'low': 1, 'informational': 0}
IMPACTS = {
    'contact_exposure': 'Publicar un canal de contacto facilita mensajes no deseados y relacionar esta cuenta con otros perfiles que muestran el mismo dato.',
    'location_disclosure': 'La ubicación publicada reduce la privacidad sobre los lugares mencionados. Una referencia precisa requiere atención prioritaria.',
    'temporal_exposure': 'Las referencias temporales exponen contexto sobre actividades o ausencias; combinarlas con ubicaciones aumenta la exposición.',
    'education_work_context': 'La institución o empresa mencionada permite conectar la actividad pública con el contexto académico o profesional.',
    'biographical_identifiers': 'Un cargo o detalle biográfico añade una pista para distinguir a la persona y relacionar sus perfiles.',
    'cross_platform_correlation': 'Los enlaces y datos compartidos permiten pasar de un perfil a otro y reunir información de contextos distintos.',
    'alias_reuse': 'Repetir un alias facilita encontrar y relacionar cuentas de plataformas distintas.',
    'public_documents': 'Un documento público puede conservar identificadores y metadatos que amplían la información visible.',
    'content_disclosure': 'La publicación contiene una señal de exposición validada por Exposure Lens; conviene revisar qué datos necesita mostrar.',
}


def assess_posts(registry, posts, exposure):
    """posts contains (fact ID, normalized text unit or None); never persist raw text.

    Assess every represented post locally, including ones outside Exposure's AI
    limits. Import model signals only from observed findings with a matching
    content source, never from account-level or inferred findings.
    """
    multiplicity = Counter(unit['source_content_id'] for _, unit in posts if unit)
    results = []
    for fact_id, unit in posts:
        fact = registry.facts[fact_id]
        if not unit:
            results.append(PostAssessment(fact_id=fact_id, status='no_text',
                explanation='No se obtuvo texto para evaluar esta publicación. Imágenes, audio y video no se analizaron.'))
            continue
        candidates = _local_signals(unit)
        for signal in candidates:
            signal['excerpt'] = unit['text']
        if exact_emails(unit['text']) or exact_phones(unit['text']):
            candidates.append(dict(category='contact_exposure', severity='medium',
                excerpt=unit['text'], method='deterministic'))
        for finding in exposure.findings:
            if finding.basis != 'observed' or finding.category not in IMPACTS:
                continue
            for evidence in finding.evidence:
                if evidence.source_type != 'content':
                    continue
                evidence_url = safe_url(evidence.url)
                same_url = bool(fact.url and evidence_url == fact.url)
                same_id = (evidence.source_id == unit['source_content_id']
                           and multiplicity[unit['source_content_id']] == 1
                           and (not evidence.platform or evidence.platform == fact.platform)
                           and (not evidence_url or not fact.url or evidence_url == fact.url))
                if same_url or same_id:
                    # The aggregate disclosure finding repeats its specific signals.
                    if finding.category == 'content_disclosure' and any(
                            category in IMPACTS and category != 'content_disclosure' for category in finding.signals):
                        continue
                    candidates.append(dict(category=finding.category, severity=finding.severity,
                        excerpt=evidence.excerpt, method=finding.analysis_method))
        strongest = {}
        for signal in candidates:
            category = signal['category']
            previous = strongest.get(category)
            if previous is None or SEVERITY[signal['severity']] > SEVERITY[previous['severity']]:
                strongest[category] = signal
        signals = []
        for category, signal in sorted(strongest.items(), key=lambda item: (-SEVERITY[item[1]['severity']], item[0])):
            observation = minimized_evidence(category, signal['excerpt'])
            ref = registry.evidence_ref(source_type='post_risk_analysis', excerpt=observation,
                entity_ids=fact.source_entity_ids, content_ids=[fact_id], platform=fact.platform, url=fact.url)
            signals.append(PostRiskSignal(category=category, label=CATEGORY_LABELS[category],
                severity=signal['severity'], observation=observation, why_it_matters=IMPACTS[category],
                recommendations=RECOMMENDATIONS.get(category, RECOMMENDATIONS['content_disclosure']),
                evidence_refs=[ref], analysis_method=signal['method']))
        if signals:
            severity = max((signal.severity for signal in signals), key=SEVERITY.get)
            labels = ', '.join(signal.label for signal in signals)
            explanation = f'Esta publicación expone {labels}. Se prioriza por su señal de mayor severidad'
            explanation += ' y por combinar varios tipos de datos.' if len(signals) > 1 else '.'
            results.append(PostAssessment(fact_id=fact_id, severity=severity, status='signals_detected',
                signals=signals, explanation=explanation,
                recommendations=list(dict.fromkeys(rec for signal in signals for rec in signal.recommendations))))
        else:
            results.append(PostAssessment(fact_id=fact_id, status='no_signals',
                explanation='No se detectaron señales en el texto con las reglas locales y los hallazgos disponibles de Exposure Lens. Esto no garantiza ausencia de riesgo.'))
    return sorted(results, key=lambda item: (-SEVERITY.get(item.severity, -1), -len(item.signals), item.fact_id))


def identity_portrait(registry, assessments):
    """Describe attributable identity and correlatability, with resolvable fact IDs."""
    facts = list(registry.facts.values())
    claims = []
    for kind, prefix in [('name', 'Nombre declarado'), ('alias', 'Aliases presentes en la huella'),
                         ('account', 'Cuentas atribuidas'), ('context', 'Contexto institucional explícito')]:
        selected = sorted((fact for fact in facts if fact.kind == kind), key=lambda fact: fact.id)
        if selected:
            claims.append(NarrativeClaim(text=prefix + ': ' + '; '.join(fact.label for fact in selected) + '.',
                fact_ids=[fact.id for fact in selected]))
    for relation_type, explanation in [
        ('SAME_ALIAS', 'El mismo alias conecta estas cuentas atribuidas. Buscarlo facilita reunir actividad de diferentes plataformas.'),
        ('SAME_EMAIL', 'Un correo público compartido conecta estas fuentes. Esa coincidencia permite unir información que se publicó en contextos distintos.'),
    ]:
        links = [relation for relation in registry.relations.values() if relation.type == relation_type]
        if links:
            claims.append(NarrativeClaim(text=explanation,
                fact_ids=sorted({key for link in links for key in (link.source, link.target)})))
    risky = [assessment for assessment in assessments if assessment.signals]
    contexts = {}
    for assessment in risky:
        for signal in assessment.signals:
            if signal.category in {'education_work_context', 'biographical_identifiers'}:
                contexts.setdefault(signal.observation, []).append(assessment.fact_id)
    for observation, fact_ids in sorted(contexts.items()):
        claims.append(NarrativeClaim(text=observation, fact_ids=sorted(set(fact_ids))))
    if risky:
        categories = sorted({signal.label for assessment in risky for signal in assessment.signals})
        claims.append(NarrativeClaim(text='Las publicaciones añaden estas piezas a la identidad pública: '
            + ', '.join(categories) + '. Combinadas pueden hacer más fácil reconocer y relacionar la huella de la persona.',
            fact_ids=[assessment.fact_id for assessment in risky]))
    return claims
