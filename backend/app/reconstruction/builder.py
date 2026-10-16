"""The registry is the single source for identity, narrative, timeline and graph.

Never reads bios, captions, post text, authorship free text or review candidates.
Only typed dataset fields and locally minimized Exposure evidence are projected.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.exposure.detectors import exact_emails, exact_phones, domain_from_url
from app.reconstruction.graph import build_graph
from app.reconstruction.narrative import build_narrative, build_timeline, content_counts
from app.reconstruction.registry import FactRegistry, fingerprint, canonical
from app.reconstruction.safety import safe_identifier, safe_platform, safe_day, minimized_evidence, safe_url as _safe_url
from app.schemas.exposure import ExposureReport
from app.schemas.reconstruction import DigitalFootprintReconstruction, ReconstructionIdentity
from app.schemas.review import ReviewedFootprintDataset
from app.services.exposure_lens import _is_attributed, CATEGORY_LABELS

RECONSTRUCTION_VERSION = 'reconstruction-v1'
GRAPH_VERSION = 'graph-v2'


def build_snapshot(dataset: ReviewedFootprintDataset, exposure: ExposureReport, *, investigation_id: str,
                   data_hash: str, exposure_hash: str, input_hash: str, config: dict,
                   generated_at: datetime | None = None) -> DigitalFootprintReconstruction:
    registry = FactRegistry()
    identity = ReconstructionIdentity()
    # Source aliases are lookup only, never facts from review/rejected records.
    sources: dict[str, str] = {}
    urls: dict[str, str] = {}
    declared_names = set()
    subject = 'subject:' + investigation_id
    ref = registry.evidence_ref(source_type='subject_declaration', excerpt='Datos proporcionados por el sujeto.')
    registry.fact(id=subject, kind='subject', label='Sujeto', basis='DECLARED', group='identity', ring=0,
                  refs=[ref], safe_summary='Centro de la huella declarada y confirmada.')

    def identifier(kind, value, basis, refs):
        clean = safe_identifier(kind, value)
        if not clean:
            return None
        key = fingerprint(kind, clean.casefold())
        registry.fact(id=key, kind=kind, label=('@' if kind == 'alias' else '') + clean,
                      basis=basis, group='identity', ring=1, refs=refs)
        return key

    for seed in sorted(dataset.subject.get('declared', []), key=lambda s: s.seed_id):
        if seed.provenance.origin != 'subject' or seed.provenance.status != 'declared':
            continue
        kind = 'alias' if seed.kind == 'username' else seed.kind
        seed_ref = registry.evidence_ref(source_type='subject_declaration',
            excerpt='Identificador declarado directamente por el sujeto.')
        key = identifier(kind, seed.value, 'DECLARED', [seed_ref])
        if key:
            identity.declared.append(key)
            registry.relate(subject, key, 'DECLARES', 'DECLARED', 'Dato proporcionado directamente por el sujeto.', [seed_ref])
            if kind == 'name':
                declared_names.add(seed.value)

    def entity_fact(record, kind, group, ring, label, summary):
        entity_id = str(record.entity_id) if record.entity_id else None
        key = 'entity:' + entity_id if entity_id else fingerprint('profile', record.seed_id or canonical(
            [record.platform, record.username, record.value]))
        platform = safe_platform(record.platform)
        url = _safe_url(record.profile_url or next(iter(record.evidence_urls), None))
        refs = [registry.evidence_ref(source_type='subject_declaration' if not entity_id and record.ownership.get('status') == 'subject_declared' else 'reviewed_entity', excerpt=summary,
                                     entity_ids=[entity_id] if entity_id else [], platform=platform, url=url)]
        basis = 'DECLARED' if record.ownership.get('status') == 'subject_declared' else 'OBSERVED'
        tools = sorted({v for v in record.source_tools if safe_platform(v)})
        display = record.display_name if record.display_name in declared_names else None
        safe_summary = summary + (f' Nombre público: {display}.' if display else '')
        registry.fact(id=key, kind=kind, label=label, basis=basis, group=group, ring=ring,
                      refs=refs, platform=platform, url=url, safe_summary=safe_summary[:500],
                      ownership_basis=record.ownership.get('status') if _is_attributed(record) else None,
                      source_tools=tools)
        for raw_id in (entity_id, record.seed_id):
            if raw_id:
                sources[raw_id] = key
        if url:
            urls[url] = key
        return key, refs

    accounts = sorted([a for a in dataset.accounts if _is_attributed(a) and a.entity_type != 'sensitive_account'],
                      key=lambda a: str(a.entity_id or a.seed_id or a.value))
    aliases = defaultdict(set)
    for account in accounts:
        username = safe_identifier('alias', account.username or '')
        platform = safe_platform(account.platform)
        label = f'{platform or "Cuenta pública"}' + (f' · @{username}' if username else '')
        declared = account.ownership.get('status') == 'subject_declared'
        why = 'Cuenta declarada por el sujeto.' if declared else 'Cuenta confirmada por el sujeto en Verification Gate.'
        key, refs = entity_fact(account, 'account', 'accounts', 2, label, why + ' Biografía minimizada.')
        identity.accounts.append(key)
        if registry.facts[key].url and account.entity_id:
            url_id = identifier('url', registry.facts[key].url, 'OBSERVED', refs)
            if url_id:
                identity.public_identifiers.append(url_id)
                registry.relate(key, url_id, 'LINKS_TO', 'OBSERVED', 'URL pública del perfil atribuido.', refs)
        registry.relate(subject, key, 'ATTRIBUTED_ACCOUNT', 'DECLARED' if declared else 'OBSERVED', why, refs)
        if username:
            alias = identifier('alias', username, 'OBSERVED' if account.entity_id else 'DECLARED', refs)
            registry.relate(key, alias, 'USES_ALIAS', 'OBSERVED' if account.entity_id else 'DECLARED',
                            'Alias explícito en el perfil atribuido.' if account.entity_id else 'Alias declarado para esta plataforma.', refs)
            if account.entity_id:
                aliases[alias].add(key)
                identity.public_identifiers.append(alias)

    for alias, account_ids in sorted(aliases.items()):
        ordered = sorted(account_ids)
        for right in ordered[1:]:
            left = ordered[0]
            refs = registry.facts[left].evidence_refs + registry.facts[right].evidence_refs
            registry.relate(left, right, 'SAME_ALIAS', 'CORRELATED',
                            f'Ambas cuentas atribuidas usan {registry.facts[alias].label}. Ownership proviene de la revisión.', refs)

    academic_ids = set()
    for profile in sorted(dataset.academic_profiles, key=lambda a: str(a.entity_id or a.seed_id or a.value)):
        if not profile.entity_id or not _is_attributed(profile):
            continue
        key, refs = entity_fact(profile, 'academic_profile', 'accounts', 2, 'Perfil académico atribuido',
                                'Perfil académico confirmado por el sujeto; sin atribuir coautores.')
        academic_ids.add(str(profile.entity_id))
        identity.academic_presence.append(key)
        registry.relate(subject, key, 'ATTRIBUTED_PROFILE', 'OBSERVED', 'Perfil académico confirmado en Verification Gate.', refs)

    for document in sorted(dataset.documents, key=lambda d: str(d.entity_id or d.value)):
        parent_id = str(document.associated_profile_entity_id)
        if not document.entity_id or parent_id not in academic_ids or document.provenance.status in {'rejected', 'uncertain'}:
            continue
        parent = sources[parent_id]
        kind = 'publication' if document.entity_type == 'academic_publication' else 'document'
        key, refs = entity_fact(document, kind, 'documents', 3,
                                'Publicación académica atribuida' if kind == 'publication' else 'Documento atribuido',
                                'Documento asociado al perfil académico por la huella revisada; título minimizado.')
        identity.documents.append(key)
        registry.relate(parent, key, 'AUTHORED' if kind == 'publication' and document.authorship_evidence.get('relation') == 'authored_work' else 'ASSOCIATED_WITH', 'OBSERVED',
                        'La huella revisada vincula este documento al perfil académico mediante su relación registrada.',
                        refs + registry.facts[parent].evidence_refs)

    posts = sorted([p for p in dataset.social_content if isinstance(p, dict)], key=lambda p: canonical({
        key: p.get(key) for key in ('account_entity_id', 'id', 'url', 'posted_at', 'published_at', 'timestamp', 'content_type')
    }))
    for post in posts:
        parent = sources.get(str(post.get('account_entity_id') or ''))
        if not parent or registry.facts[parent].kind != 'account':
            continue
        url = _safe_url(post.get('url'))
        external_id = post.get('id')
        # Text is deliberately not a fallback ID source.
        if not external_id and not url:
            continue
        stable = canonical([parent, str(external_id or url)])
        key = fingerprint('content', stable)
        kind = 'post'
        if post.get('content_type') == 'repository' and registry.facts[parent].platform == 'github' and url:
            parts = urlsplit(url)
            owner = registry.facts[parent].label.split('@')[-1]
            segments = parts.path.strip('/').split('/')
            if parts.hostname == 'github.com' and len(segments) >= 2 and segments[0].casefold() == owner.casefold():
                kind = 'repository'
        ref = registry.evidence_ref(source_type='public_content', excerpt='Contenido público observado en una cuenta atribuida.',
            entity_ids=registry.facts[parent].source_entity_ids,
            content_ids=[key], platform=registry.facts[parent].platform, url=url)
        registry.fact(id=key, kind=kind, label='Repositorio público' if kind == 'repository' else 'Publicación pública',
                      basis='OBSERVED', group='content', ring=3, refs=[ref], platform=registry.facts[parent].platform,
                      url=url, safe_summary='Contenido público atribuido; texto original omitido.',
                      date=safe_day(post.get('posted_at') or post.get('published_at') or post.get('timestamp')))
        identity.public_content.append(key)
        registry.relate(parent, key, 'PUBLISHED', 'OBSERVED', 'La publicación pertenece a esta cuenta según la huella revisada.', [ref])
        if external_id:
            # Same external ID across platforms is ambiguous: URL is still precise.
            old = sources.get(str(external_id))
            sources[str(external_id)] = key if old in {None, key} else ''
        if url:
            urls[url] = key

    # Only attributed structured emails can connect to breach records. Public
    # exposure alone never promotes an identifier into ownership.
    attributed_emails = {safe_identifier('email', e.value) for e in dataset.emails if _is_attributed(e)}
    attributed_emails.update(safe_identifier('email', s.value) for s in dataset.subject.get('declared', [])
                             if s.kind == 'email' and s.provenance.status == 'declared' and s.provenance.origin == 'subject')
    attributed_emails.discard(None)
    for record in sorted([*dataset.emails, *dataset.phones], key=lambda e: str(e.entity_id or e.value)):
        if not _is_attributed(record):
            continue
        kind = 'email' if record.entity_type == 'email' else 'phone'
        ref = registry.evidence_ref(source_type='reviewed_identifier', excerpt='Identificador atribuido en la huella revisada.',
                                   entity_ids=[str(record.entity_id)] if record.entity_id else [])
        key = identifier(kind, record.value, 'DECLARED' if record.ownership.get('status') == 'subject_declared' else 'OBSERVED', [ref])
        if key:
            registry.relate(subject, key, 'USES_EMAIL' if kind == 'email' else 'USES_PHONE',
                            registry.facts[key].basis, 'Identificador atribuido por declaración o confirmación.', [ref])
            if record.entity_id:
                sources[str(record.entity_id)] = key

    for breach in sorted(dataset.breaches, key=lambda b: str(b.entity_id)):
        email = safe_identifier('email', breach.email)
        if email not in attributed_emails or breach.provenance.status in {'rejected', 'uncertain'}:
            continue
        key = 'entity:' + str(breach.entity_id)
        ref = registry.evidence_ref(source_type='breach_record', excerpt='Exposición observada; no prueba identidad.',
                                   entity_ids=[str(breach.entity_id)], url=next((_safe_url(u) for u in breach.evidence_urls if _safe_url(u)), None))
        email_id = identifier('email', email, 'OBSERVED', [ref])
        registry.fact(id=key, kind='breach', label='Registro de exposición en brecha', basis='OBSERVED', group='breaches', ring=3,
                      refs=[ref], safe_summary=f'Correo atribuido presente en {len(breach.breaches) or 1} registro(s) de brecha. '
                      'Exposición observada; no prueba identidad.')
        sources[str(breach.entity_id)] = key
        identity.breach_exposure.append(key)
        registry.relate(email_id, key, 'EXPOSED_IN_BREACH', 'OBSERVED',
                        'El correo atribuido figura en un registro de exposición; esto no prueba identidad ni ownership.', [ref])

    public_email_sources = defaultdict(set)
    finding_refs = {}
    finding_sources = {}
    findings = sorted([f for f in exposure.findings if f.basis == 'observed'], key=lambda f: f.id)
    for finding in findings:
        refs, linked = [], set()
        for evidence in sorted(finding.evidence, key=lambda e: canonical(e.model_dump(mode='json'))):
            url = _safe_url(evidence.url)
            source = sources.get(evidence.source_id or '') or (urls.get(url) if url else None)
            if source not in registry.facts:
                continue
            origin = registry.facts[source]
            ref = registry.evidence_ref(source_type='exposure_evidence',
                excerpt=minimized_evidence(finding.category, evidence.excerpt or ''),
                entity_ids=origin.source_entity_ids, content_ids=origin.source_content_ids,
                platform=origin.platform, url=url)
            refs.append(ref)
            linked.add(source)
            if finding.category == 'contact_exposure' and origin.kind in {'account', 'post', 'document', 'publication', 'academic_profile'}:
                contacts = [('email', v) for v in exact_emails(evidence.excerpt or '')]
                contacts += [('phone', v) for v in exact_phones(evidence.excerpt or '')]
                for kind, value in contacts:
                    contact = identifier(kind, value, 'OBSERVED', [ref])
                    if contact:
                        identity.public_identifiers.append(contact)
                        registry.relate(source, contact, 'PUBLIC_EMAIL_ON' if kind == 'email' else 'PUBLIC_PHONE_ON',
                                        'OBSERVED', 'Identificador publicado explícitamente en esta fuente atribuida.', [ref])
                        if kind == 'email':
                            public_email_sources[contact].add(source)
            if finding.category == 'education_work_context':
                text = minimized_evidence(finding.category, evidence.excerpt or '')
                context = fingerprint('context', text)
                registry.fact(id=context, kind='context', label=text[:160], basis='OBSERVED', group='documents', ring=3,
                              refs=[ref], safe_summary='Contexto institucional explícito, minimizado por Exposure Lens.')
                identity.academic_presence.append(context)
                registry.relate(context, source, 'MENTIONED_IN', 'OBSERVED', 'Este contexto institucional aparece explícitamente en la fuente atribuida.', [ref])
            if finding.category in {'contact_exposure', 'cross_platform_correlation'} and url:
                domain = domain_from_url(url)
                if domain and finding.signals and 'mismo_dominio' in finding.signals:
                    domain_id = identifier('domain', domain, 'OBSERVED', [ref])
                    if domain_id:
                        identity.public_identifiers.append(domain_id)
                        registry.relate(source, domain_id, 'LINKS_TO', 'OBSERVED', 'Enlace público observado en esta fuente.', [ref])
        # Trusted finding IDs are not enough: require a resolvable reviewed source.
        finding_refs[finding.id] = sorted(set(refs))
        finding_sources[finding.id] = sorted(linked)
        if finding.category == 'cross_platform_correlation' and 'enlace_explicito' in finding.signals:
            # Existence of a cross-link is observed, its direction is not inferred
            # from the unordered source list. Parse only explicit evidence URLs.
            for e in finding.evidence:
                source = sources.get(e.source_id or '')
                target = urls.get(_safe_url(e.url))
                if source and target and source != target and refs:
                    registry.relate(source, target, 'LINKS_TO', 'OBSERVED', 'Exposure Lens observó un enlace directo entre estos perfiles.', refs)

    for email, source_ids in sorted(public_email_sources.items()):
        ordered = sorted(source_ids, key=lambda key: (registry.facts[key].kind not in {'account', 'academic_profile'}, key))
        for right in ordered[1:]:
            left = ordered[0]
            refs = [ref for relation in registry.relations.values()
                    if relation.type == 'PUBLIC_EMAIL_ON' and relation.target == email and relation.source in {left, right}
                    for ref in relation.evidence_refs]
            registry.relate(left, right, 'SAME_EMAIL', 'CORRELATED',
                            'El mismo correo fue observado públicamente en ambas fuentes; no modifica ownership.', refs)

    for finding in findings:
        refs = finding_refs[finding.id]
        linked = finding_sources[finding.id]
        if not refs or not linked:
            continue
        key = 'exposure:' + finding.id
        # Labels are local category descriptions; never reproduce model prose.
        label = CATEGORY_LABELS.get(finding.category, 'Señal pública de exposición')
        registry.fact(id=key, kind='exposure', label=label, basis='OBSERVED', group='exposure', ring=4,
                      refs=refs, severity=finding.severity,
                      safe_summary='Señal de Exposure Lens. ' + ('Detectada por regla local.' if finding.analysis_method == 'deterministic'
                                                                 else 'Clasificada con IA y limitada por reglas locales.'))
        for source in linked:
            registry.relate(source, key, 'HAS_EXPOSURE_SIGNAL', 'OBSERVED',
                            'Esta fuente es evidencia del hallazgo; la severidad pertenece al hallazgo.', refs)

    for key in set(identity.public_identifiers):
        fact = registry.facts[key]
        fact.safe_summary = ('Identificador declarado también observado públicamente.' if fact.basis == 'DECLARED'
                             else 'Identificador observado explícitamente en una fuente atribuida.')

    for field in type(identity).model_fields:
        setattr(identity, field, sorted(set(getattr(identity, field))))
    facts = sorted(registry.facts.values(), key=lambda f: (f.ring, f.id))
    counts = dict(sorted(Counter(f.kind for f in facts).items()))
    counts['public_identifiers'] = len(identity.public_identifiers)
    partial = exposure.status == 'partial' or bool(dataset.execution.get('acquisition_partial'))
    return DigitalFootprintReconstruction(
        investigation_id=investigation_id, dataset_hash=data_hash, exposure_dataset_hash=exposure.dataset_hash,
        exposure_hash=exposure_hash, input_hash=input_hash, coverage='partial' if partial else 'observed',
        coverage_reasons=sorted(set([*exposure.partial_reasons, *(['acquisition_partial'] if dataset.execution.get('acquisition_partial') else [])])),
        identity=identity, facts=facts, evidence=dict(sorted(registry.evidence.items())),
        correlations=sorted(registry.relations.values(), key=lambda e: e.id), summary=build_narrative(registry),
        counts=counts, content_by_platform=content_counts(registry), exposure_summary=exposure.summary,
        timeline=build_timeline(registry, config['reconstruction_max_timeline_items']), graph=build_graph(registry, config),
        generated_at=generated_at or datetime.now(timezone.utc),
    )
