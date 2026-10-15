"""Observed evidence and visual affinity. Weights are not identity probabilities."""
import re
import unicodedata
from functools import lru_cache
from urllib.parse import parse_qsl, urlsplit

from app.tools.phone_numbers import phone_identity
from app.tools.social_profiles import parse_social_profile, normalize_web_url
from app.tools.academic_metadata import orcid_url

POLICY_VERSION = 2
BOUND_TYPES = {'breach', 'infostealer', 'email_registration'}
PROFILE_TYPES = {'social_account', 'sensitive_account', 'google_account', 'academic_profile'}
STRONG_EMAIL_ROLES = {'declared_email', 'profile_email', 'bio_contact', 'lookup_email', 'identifier'}
STRONG_PHONE_ROLES = {'profile_phone', 'identifier'}
LABELS = {'email': 'correo coincidente', 'phone': 'teléfono coincidente', 'username': 'alias coincidente',
    'name': 'nombre completo coincidente', 'orcid': 'ORCID coincidente', 'gaia_id': 'GAIA coincidente',
    'affiliation': 'afiliación coincidente', 'registration': 'señal de registro del correo',
    'mention': 'identificador mencionado', 'profile_link': 'enlace explícito de perfil'}


def signal_label(item):
    return {'lookup_email': 'correo asociado por consulta exacta al proveedor',
        'commit_email': 'correo en autoría de commit; señal contextual',
        'mention_email': 'correo mencionado; sin declaración de contacto',
        'candidate_email': 'correo candidato sin corroboración de perfil',
        'queried_username': 'alias consultado; sin corroboración adicional',
        'observed_username': 'alias coincidente; señal débil por sí sola',
        'mention_phone': 'teléfono mencionado; señal contextual'}.get(item['role'], LABELS.get(item['kind'], item['kind']))


def strings(value):
    return [item.strip() for item in value[:100] if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def email_key(value):
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    return value if len(value) <= 320 and re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', value) else None


def name_key(value):
    if not isinstance(value, str) or len(value) > 500:
        return None
    folded = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    parts = re.findall(r'[^\W\d_]+', folded)
    if len(parts) < 2 or any(len(part) < 2 for part in parts) or len(parts) > 8:
        return None
    return ' '.join(parts)


@lru_cache(maxsize=8192)
def resource_key(value):
    if not isinstance(value, str):
        return None
    normalized = normalize_web_url(value, keep_query=True)
    if not normalized:
        return None
    profile = parse_social_profile(normalized)
    if profile:
        from app.schemas.identifiers import CASE_SENSITIVE_TYPES
        identifier = profile.username if profile.resource_kind in CASE_SENSITIVE_TYPES | {'channel_id'} else profile.username.casefold()
        return (profile.platform, profile.resource_kind, identifier)
    parsed = urlsplit(normalized)
    query = tuple(sorted((k, v) for k, v in parse_qsl(parsed.query) if not k.startswith('utm_') and k not in {'fbclid', 'ref'}))
    return (parsed.hostname.removeprefix('www.'), parsed.path.rstrip('/'), query)


def is_profile(entity):
    return entity.entity_type in PROFILE_TYPES or (entity.entity_type == 'academic' and entity.platform == 'openalex_author')


def signals(entity):
    """Normalize roles without scraping arbitrary text, query echoes or collaborators."""
    meta = entity.metadata_info or {}
    preserved = meta.get('correlation_observations')
    if meta.get('correlation_observations_version') == POLICY_VERSION and isinstance(preserved, list):
        return [dict(item) for item in preserved[:200] if isinstance(item, dict)
            and isinstance(item.get('kind'), str) and isinstance(item.get('value'), str)
            and isinstance(item.get('role'), str) and item.get('kind') in LABELS]
    tool = str(entity.source_tool or meta.get('source_tool') or '').rsplit(':', 1)[-1]
    profile = is_profile(entity)
    verified = meta.get('verification_status') == 'verified' or tool in {'github_deep_scanner', 'gravatar_deep', 'keybase_resolver'}
    legacy_declared = profile and meta.get('verification_status') not in {'candidate', 'blocked', 'inconclusive'}
    result = []
    def add(kind, value, role, field):
        normalize = {'email': email_key, 'phone': phone_identity, 'name': name_key}.get(kind)
        value = normalize(value) if normalize else value
        if value and not any(s['kind'] == kind and s['value'] == value and s['role'] == role for s in result):
            result.append({'kind': kind, 'value': value, 'role': role, 'field': field,
                'source_tool': tool,
                'source_url': entity.value if str(entity.value).startswith('http') else None})
    if entity.entity_type in BOUND_TYPES:
        return []
    if entity.entity_type == 'email':
        add('email', entity.value, 'identifier', 'value')
    if entity.entity_type == 'phone':
        add('phone', entity.value, 'identifier', 'value')
    email_role = 'declared_email' if legacy_declared or verified else 'candidate_email' if profile else 'mention_email'
    commit_emails = {email_key(item.get('email')) for item in meta.get('email_evidence', []) if isinstance(item, dict)} if isinstance(meta.get('email_evidence'), list) else set()
    for value in strings(meta.get('emails')):
        role = 'commit_email' if tool == 'github_deep_scanner' and (email_key(value) in commit_emails or 'profile_email' not in meta) else email_role
        add('email', value, role, 'emails')
    if profile:
        for key in ('profile_email', 'public_email'):
            if verified or legacy_declared or entity.entity_type == 'google_account':
                add('email', meta.get(key), 'profile_email', key)
        if meta.get('association_evidence') == 'exact_public_profile_email' and verified:
            add('email', meta.get('matched_email'), 'profile_email', 'matched_email')
        if tool == 'gravatar_deep':
            add('email', meta.get('email'), 'lookup_email', 'email')
        if entity.entity_type == 'google_account' and meta.get('technique') == 'ghunt_people_profile' and meta.get('account_exists') is True:
            add('email', meta.get('queried_email'), 'lookup_email', 'queried_email')
        for value in strings(meta.get('extracted_emails')):
            # A contact in a verified bio is observed, but remains a declaration.
            role = 'bio_contact' if verified and tool != 'github_deep_scanner' else 'commit_email' if email_key(value) in commit_emails else email_role
            add('email', value, role, 'extracted_emails')
    else:
        for value in strings(meta.get('extracted_emails')):
            add('email', value, 'mention_email', 'extracted_emails')
    for key in ('phones', 'extracted_phones'):
        for value in strings(meta.get(key)):
            add('phone', value, 'profile_phone' if profile and (verified or legacy_declared) else 'mention_phone', key)
    if profile:
        username = meta.get('username') or meta.get('preferred_username')
        if isinstance(username, str) and re.fullmatch(r'[\w.-]{2,100}', username) and meta.get('resource_kind', 'username') == 'username':
            add('username', username.casefold(), 'observed_username' if verified or legacy_declared else 'queried_username', 'username')
        for key in ('name', 'full_name', 'author_name'):
            add('name', meta.get(key), 'profile_name', key)
        if tool == 'gravatar_deep':
            add('name', meta.get('display_name'), 'profile_name', 'display_name')
        for key in ('institutions',):
            for value in strings(meta.get(key)):
                add('affiliation', name_key(value), 'profile_affiliation', key)
        if isinstance(meta.get('company_university'), str):
            add('affiliation', name_key(meta['company_university']), 'profile_affiliation', 'company_university')
        orcid = orcid_url(meta.get('orcid')) or orcid_url(entity.value)
        if orcid:
            add('orcid', orcid.rsplit('/', 1)[-1], 'profile_identifier', 'orcid')
        gaia = meta.get('gaia_id')
        if entity.entity_type == 'google_account' and isinstance(gaia, str) and re.fullmatch(r'[0-9]{10,30}', gaia):
            add('gaia_id', gaia, 'profile_identifier', 'gaia_id')
    # A structured DNI row is contextual documentary evidence, not a profile.
    if meta.get('name_association') == 'structured_same_record':
        add('name', meta.get('full_name'), 'record_name', 'full_name')
    for report in meta.get('external_reports', []) if isinstance(meta.get('external_reports'), list) else []:
        if not isinstance(report, dict):
            continue
        for item in report.get('identifiers', []) if isinstance(report.get('identifiers'), list) else []:
            if isinstance(item, dict) and item.get('kind') in {'name', 'email'}:
                add(item['kind'], item.get('value'), 'agent_page_mention' if report.get('evidence_level') == 'page_content' else 'agent_search_mention', 'external_reports')
    return result


def strong_values(items, kind):
    roles = STRONG_EMAIL_ROLES if kind == 'email' else STRONG_PHONE_ROLES if kind == 'phone' else {'profile_identifier'}
    return {item['value'] for item in items if item['kind'] == kind and item['role'] in roles}


def target_affinity(entity, target):
    observed = signals(entity)
    matched = []
    expected_email = email_key(target.email)
    expected_phone = phone_identity(target.phone) if target.phone else None
    for item in observed:
        if ((item['kind'] == 'email' and item['value'] == expected_email)
                or (item['kind'] == 'phone' and item['value'] == expected_phone)
                or (item['kind'] == 'name' and item['value'] == name_key(target.full_name))
                or (item['kind'] == 'username' and isinstance(target.username, str) and item['value'] == target.username.casefold())
                or (item['kind'] == 'affiliation' and item['value'] == name_key(target.university))):
            matched.append(item)
    ids = (target.extra_data or {}).get('identifiers', [])
    ids = ids if isinstance(ids, list) else []
    for item in observed:
        if item['kind'] in {'orcid', 'gaia_id'} and any(isinstance(value, dict) and value.get('id_type') == item['kind'] and value.get('value') == item['value'] for value in ids):
            matched.append(item)
    email = any(s['kind'] == 'email' and s['role'] in STRONG_EMAIL_ROLES for s in matched)
    phone = any(s['kind'] == 'phone' and s['role'] in STRONG_PHONE_ROLES for s in matched)
    stable = any(s['kind'] in {'orcid', 'gaia_id'} for s in matched)
    name = any(s['kind'] == 'name' for s in matched)
    alias = any(s['kind'] == 'username' and s['role'] == 'observed_username' for s in matched)
    weight = 0.0
    if email:
        weight = 0.72 if all(s['role'] == 'lookup_email' for s in matched if s['kind'] == 'email') else 0.82
    if phone:
        weight = max(weight, 0.78)
    if stable:
        weight = max(weight, 0.72)
    if email or phone or stable:
        weight = min(0.94, weight + (0.06 if email and alias else 0) + (0.04 if name else 0) + (0.04 if email and phone else 0))
    elif name:
        weight = 0.20 if any(s['kind'] == 'affiliation' for s in matched) else 0.12
    elif any(s['kind'] in {'email', 'phone'} for s in matched):
        weight = 0.16  # Mention/candidate evidence cannot become a declared contact.
    # Alias-only matches have zero target attraction, irrespective of repeats.
    level = 'strong' if weight >= 0.65 else 'context' if weight > 0 else 'none'
    if entity.entity_type in {'breach', 'infostealer'}:
        level, weight = 'identifier_record', 0.0
    if entity.entity_type == 'email_registration':
        if email_key((entity.metadata_info or {}).get('email')) == expected_email and expected_email:
            level, weight = 'registration', 0.35
    return {'policy_version': POLICY_VERSION, 'weight': round(weight, 3), 'level': level,
        'reasons': list(dict.fromkeys(signal_label(s) for s in matched)),
        'signals': matched, 'ownership_status': 'unverified',
        'semantics': 'visual_priority_not_identity_probability', 'inherited': False}


def pair_evidence(left, right, left_signals=None, right_signals=None):
    """Typed relationships. No transitive attribution and no substring URL links."""
    if left.entity_type in BOUND_TYPES or right.entity_type in BOUND_TYPES:
        return []
    a = signals(left) if left_signals is None else left_signals
    b = signals(right) if right_signals is None else right_signals
    ma, mb = left.metadata_info or {}, right.metadata_info or {}
    result = []
    def add(kind, grouping, values, weight):
        result.append((kind, grouping, {**values, 'visual_weight': weight,
            'semantics': 'observed_relation_not_ownership', 'policy_version': POLICY_VERSION}))
    emails = strong_values(a, 'email') & strong_values(b, 'email')
    phones = strong_values(a, 'phone') & strong_values(b, 'phone')
    usernames = {s['value'] for s in a if s['kind'] == 'username' and s['role'] == 'observed_username'} & {s['value'] for s in b if s['kind'] == 'username' and s['role'] == 'observed_username'}
    if emails:
        lookup = any(s['kind'] == 'email' and s['value'] in emails and s['role'] == 'lookup_email' for s in [*a, *b])
        kind = 'email_lookup_association' if lookup else 'shares_email_and_username' if usernames else 'shares_declared_email'
        add(kind, True, {'emails': sorted(emails), **({'usernames': sorted(usernames)} if usernames else {})},
            0.72 if lookup else 0.88 if usernames else 0.82)
    elif usernames and not (str(left.source_tool or '').rsplit(':', 1)[-1] == str(right.source_tool or '').rsplit(':', 1)[-1]
            and str(left.source_tool or '').rsplit(':', 1)[-1] in {'username_finder', 'maigret_enricher', 'ghunt', 'email_enumerator'}):
        add('same_username', False, {'username': sorted(usernames)[0]}, 0.03)
    if phones:
        add('publishes_phone' if 'phone' in {left.entity_type, right.entity_type} else 'shares_declared_phone', True, {'phones': sorted(phones)}, 0.78)
    for source, other in ((left, right), (right, left)):
        other_key = resource_key(other.value)
        links = strings((source.metadata_info or {}).get('linked_profiles'))
        if other_key and any(resource_key(url) == other_key for url in links):
            add('explicit_profile_link', is_profile(source) and is_profile(other), {'source_url': source.value, 'linked_profile': other.value}, 0.65)
            break
    for kind in ('orcid', 'gaia_id'):
        common = strong_values(a, kind) & strong_values(b, kind)
        if common:
            add('shared_' + kind, True, {kind: sorted(common)}, 0.72)
    for work, author in ((left, right), (right, left)):
        if work.platform != 'research_paper' or not is_profile(author):
            continue
        metadata = work.metadata_info or {}
        ids = strings(metadata.get('matched_author_ids'))
        author_orcids = strong_values(signals(author), 'orcid')
        matched_orcids = set()
        for record in metadata.get('academic_records', []) if isinstance(metadata.get('academic_records'), list) else []:
            for item in record.get('matched_authors', []) if isinstance(record, dict) and isinstance(record.get('matched_authors'), list) else []:
                value = orcid_url(item.get('orcid')) if isinstance(item, dict) else None
                if value:
                    matched_orcids.add(value.rsplit('/', 1)[-1])
        if author.value in ids or author_orcids & matched_orcids:
            add('authored_work', False, {'author_url': author.value, 'work_url': work.value, 'basis': 'observed_author_identifier'}, 0.55)
    names = {s['value'] for s in a if s['kind'] == 'name'} & {s['value'] for s in b if s['kind'] == 'name'}
    if names and not emails and not phones:
        affiliations = {s['value'] for s in a if s['kind'] == 'affiliation'} & {s['value'] for s in b if s['kind'] == 'affiliation'}
        add('name_and_affiliation' if affiliations else 'same_name', False,
            {'names': sorted(names), **({'affiliations': sorted(affiliations)} if affiliations else {})}, 0.22 if affiliations else 0.12)
    if not phones:
        for phone_node, source in ((left, right), (right, left)):
            if phone_node.entity_type == 'phone':
                number = phone_identity(phone_node.value)
                if number and any(s['kind'] == 'phone' and s['value'] == number for s in signals(source)):
                    add('mentions_phone', False, {'phone': number, 'source_url': source.value}, 0.12)
    return result


def projection(entities, target, relationships, affinities=None):
    result = affinities if affinities is not None else {str(e.id): target_affinity(e, target) for e in entities}
    for entity in entities:
        key = str(entity.id)
        if result[key]['weight'] >= 0.65 or entity.entity_type in BOUND_TYPES:
            continue
        candidates = []
        for edge in relationships:
            source, destination = str(edge.source_entity_id), str(edge.target_entity_id)
            neighbor = destination if source == key else source if destination == key else None
            if (neighbor in result and result[neighbor]['weight'] >= 0.12
                    and result[neighbor]['weight'] > result[key]['weight'] and edge.relation_type != 'same_username'):
                candidates.append((result[neighbor]['weight'], float((edge.evidence or {}).get('visual_weight', 0.1)), neighbor, edge.relation_type))
        if candidates:
            _, _, parent, relation = sorted(candidates, key=lambda item: (-item[0], -item[1], item[2]))[0]
            result[key].update(placement_parent_id=parent, placement_relation=relation,
                placement_semantics='neighbor_evidence_does_not_inherit_target_affinity')
    return result
