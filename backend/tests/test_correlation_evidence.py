"""Correlation weights position evidence; they never assert account ownership."""
from types import SimpleNamespace
import uuid

import pytest

from app.engine.persistence import infer_relationships, detect_relationships
from app.identity.evidence import signals, target_affinity
from app.identity.projection import project_evidence
from app.models.entity import Entity
from app.models.target import Target
from app.api.v1.graph import build_evidence_graph

EMAIL = 'audit@example.org'
PHONE = '+51987654321'


def entity(value='https://github.com/audit', kind='social_account', metadata=None, source='social_verifier', platform=None):
    return Entity(id=uuid.uuid4(), entity_type=kind, platform=platform, value=value,
        display_name=value, metadata_info=metadata or {}, source_tool=source)


def profile(**metadata):
    return entity(metadata={'verification_status':'verified', **metadata})


def test_alias_only_never_attracts_to_target_even_with_old_confidence_or_avatar():
    node = profile(username='audit', avatar_url='https://example.org/avatar.png', confidence=1, verification_score=1)
    score = target_affinity(node, Target(username='audit', email=EMAIL))
    assert score['weight'] == 0 and score['ownership_status'] == 'unverified'
    assert score['semantics'] == 'visual_priority_not_identity_probability'


def test_public_email_beats_alias_and_username_only_adds_support_with_email():
    target = Target(email=EMAIL, username='audit')
    email = target_affinity(profile(emails=[EMAIL.upper()]),target)
    combined = target_affinity(profile(emails=[EMAIL], username='audit'),target)
    assert 0.65 < email['weight'] < combined['weight'] < 1
    assert combined['inherited'] is False


def test_verified_profile_bio_email_and_exact_github_public_email_are_supported():
    target = Target(email=EMAIL)
    assert target_affinity(profile(extracted_emails=[EMAIL]),target)['level'] == 'strong'
    node = profile(matched_email=EMAIL, association_evidence='exact_public_profile_email')
    assert target_affinity(node,target)['level'] == 'strong'


def test_query_echoes_and_candidate_emails_do_not_equal_public_declarations():
    target = Target(email=EMAIL)
    node = entity(metadata={'verification_status':'candidate','emails':[EMAIL],'queried_email':EMAIL})
    assert target_affinity(node,target)['weight'] < 0.2
    assert target_affinity(profile(queried_email=EMAIL),target)['weight'] == 0
    wrong = profile(emails=['other'+EMAIL])
    assert target_affinity(wrong,target)['weight'] == 0


def test_github_commit_email_is_context_until_observed_on_profile():
    commit = entity(source='github_deep_scanner', metadata={'emails':[EMAIL], 'extracted_emails':[EMAIL],
        'email_evidence':[{'email':EMAIL,'commit_url':'https://github.com/audit/repo/commit/a'}]})
    assert target_affinity(commit,Target(email=EMAIL))['weight'] < 0.2
    commit.metadata_info = {**commit.metadata_info,'profile_email':EMAIL}
    assert target_affinity(commit,Target(email=EMAIL))['level'] == 'strong'


def test_ghunt_lookup_is_association_not_collaborator_or_play_games_match():
    target = Target(email=EMAIL)
    google = entity(kind='google_account', metadata={'technique':'ghunt_people_profile','account_exists':True,'queried_email':EMAIL})
    assert target_affinity(google,target)['weight'] == .72
    document = entity(kind='document', metadata={'participants':[{'email':EMAIL}], 'queried_identifier':EMAIL})
    player = profile(queried_identifier=EMAIL, engine='ghunt', query_kind='email')
    assert target_affinity(document,target)['weight'] == target_affinity(player,target)['weight'] == 0


def test_phone_matching_is_normalized_and_declared_contacts_are_stronger_than_mentions():
    target = Target(phone=PHONE)
    assert target_affinity(profile(phones=['987 654 321']),target)['level'] == 'strong'
    mention = entity(kind='search_mention',metadata={'extracted_phones':['987654321']})
    assert target_affinity(mention,target)['weight'] < .2
    wrong = profile(phones=['+51912345678'])
    assert target_affinity(wrong,target)['weight'] == 0


def test_names_are_full_observed_values_not_query_titles_or_inferences():
    target = Target(full_name='Ana Pérez')
    assert target_affinity(profile(name='Ana Perez'),target)['weight'] == .12
    assert target_affinity(profile(name='Ana Maria Perez'),target)['weight'] == 0
    assert target_affinity(profile(query_name='Ana Pérez',inferred_name='Ana Pérez'),target)['weight'] == 0
    fake_title = profile()
    fake_title.display_name = 'Ana Pérez'
    assert target_affinity(fake_title,target)['weight'] == 0


def test_shared_contacts_form_local_relations_between_profiles_without_identifier_node():
    a, b = profile(emails=[EMAIL], username='audit'), profile(emails=[EMAIL], username='audit')
    assert detect_relationships(a,b)[0][0:2] == ('shares_email_and_username',True)
    a, b = profile(phones=[PHONE]),profile(phones=['987654321'])
    assert detect_relationships(a,b)[0][0:2] == ('shares_declared_phone',True)


def test_profile_links_require_exact_canonical_resource_not_prefix_or_host_spoofing():
    target = entity('https://instagram.com/audit')
    for link in ['https://instagram.com/audit-other','https://instagram.com.evil.test/audit',
                 'https://evil.test/?next=https://instagram.com/audit']:
        assert detect_relationships(profile(linked_profiles=[link]),target) == []
    assert detect_relationships(profile(linked_profiles=['https://www.instagram.com/audit/?utm_source=test']),target)[0][0] == 'explicit_profile_link'


@pytest.mark.asyncio
async def test_name_neighbor_does_not_inherit_target_email_or_merge_identity_groups():
    anchor = profile(emails=[EMAIL],name='Ana Perez')
    neighbor = profile(name='Ana Pérez')
    unrelated = profile(name='Other Person')
    edges,groups,affinities = await project_evidence(uuid.uuid4(),[anchor,neighbor,unrelated],Target(email=EMAIL))
    assert len(groups) == 3
    assert affinities[str(neighbor.id)]['weight'] == 0
    assert affinities[str(neighbor.id)]['placement_parent_id'] == str(anchor.id)
    assert affinities[str(neighbor.id)]['inherited'] is False
    assert 'placement_parent_id' not in affinities[str(unrelated.id)]
    assert any(edge.relation_type == 'same_name' and not edge.supports_group for edge in edges)


@pytest.mark.asyncio
async def test_shared_email_component_does_not_inherit_other_members_target_relationship():
    a = profile(emails=[EMAIL, 'secondary@example.org'])
    b = profile(emails=['secondary@example.org'])
    _,groups,affinities = await project_evidence(uuid.uuid4(),[a,b],Target(email=EMAIL))
    assert len(groups) == 1
    assert affinities[str(a.id)]['level'] == 'strong' and affinities[str(b.id)]['weight'] == 0
    assert groups[0].evidence['semantics'] == 'shared_observations_not_same_person'


@pytest.mark.asyncio
async def test_large_email_component_stays_connected_with_bounded_edges():
    nodes = [profile(emails=[EMAIL]) for _ in range(120)]
    edges,groups,_ = await project_evidence(uuid.uuid4(),nodes,Target(email=EMAIL))
    assert len(groups) == 1 and len(groups[0].entity_ids) == 120
    assert 119 <= len(edges) <= 120*6


@pytest.mark.asyncio
async def test_graph_refreshes_old_entities_without_rescan_and_removes_url_heuristics():
    target = Target(id=uuid.uuid4(),email=EMAIL,username='audit')
    wrong = entity('https://example.org/'+EMAIL+'-other', metadata={'avatar_url':'https://example.org/a.png'})
    actual = profile(matched_email=EMAIL, association_evidence='exact_public_profile_email')
    investigation = SimpleNamespace(id=uuid.uuid4(),target=target,entities=[wrong,actual],relationships=[],correlation_groups=[])
    graph = await build_evidence_graph(investigation)
    roots = {edge.target:edge for edge in graph.edges if edge.id.startswith('source-')}
    assert roots['ent-'+str(wrong.id)].relation_type == 'discovered_from'
    assert roots['ent-'+str(actual.id)].relation_type == 'target_email_match'
    assert all(node.data.correlation.get('ownership_status') == 'unverified' for node in graph.nodes if not node.data.is_root)


@pytest.mark.asyncio
async def test_graph_phone_match_does_not_promote_contextual_email_to_declared_contact():
    target = Target(id=uuid.uuid4(), email=EMAIL, phone=PHONE)
    node = entity(PHONE, kind='phone', metadata={'extracted_emails': [EMAIL]})
    investigation = SimpleNamespace(id=uuid.uuid4(), target=target, entities=[node], relationships=[])
    graph = await build_evidence_graph(investigation)
    assert graph.edges[0].relation_type == 'target_phone_match'
    assert graph.nodes[1].data.correlation['weight'] == 0.78


@pytest.mark.asyncio
async def test_query_bound_records_never_link_accounts_as_common_owners():
    record = entity(EMAIL,kind='breach',metadata={'email':EMAIL})
    registration = entity(EMAIL,kind='email_registration',metadata={'email':EMAIL})
    account = profile(emails=[EMAIL])
    assert detect_relationships(record,account) == detect_relationships(registration,account) == []
    assert target_affinity(registration,Target(email=EMAIL))['level'] == 'registration'
    assert target_affinity(record,Target(email=EMAIL))['weight'] == 0


def test_orcid_author_to_work_is_a_local_documented_relationship():
    orcid = 'https://orcid.org/0000-0002-1825-0097'
    author = entity('https://openalex.org/A1',kind='academic',platform='openalex_author',metadata={'author_name':'Ana Perez','orcid':orcid})
    work = entity('https://doi.org/10.5555/test',kind='academic',platform='research_paper',metadata={'matched_author_ids':['https://openalex.org/A1']})
    assert any(kind == 'authored_work' and not grouped for kind,grouped,_ in detect_relationships(author,work))


def test_deduplication_never_promotes_candidate_email_when_other_source_verifies_profile():
    from app.engine.persistence import dedupe_findings
    from app.tools.base import ToolFinding
    candidate = ToolFinding(entity_type='social_account',value='https://github.com/audit',
        metadata_info={'source_tool':'username_finder','verification_status':'candidate','extracted_emails':[EMAIL]})
    verified = ToolFinding(entity_type='social_account',value='https://github.com/audit',
        metadata_info={'source_tool':'social_verifier','verification_status':'verified','extracted_emails':['other@example.org']})
    merged = dedupe_findings([candidate,verified])[0]
    node = entity(merged.value,metadata=merged.metadata_info)
    assert target_affinity(node,Target(email=EMAIL))['weight'] < .2
    assert target_affinity(node,Target(email='other@example.org'))['level'] == 'strong'
    repeated = dedupe_findings([merged])[0]
    assert signals(entity(repeated.value,metadata=repeated.metadata_info)) == signals(node)


def test_agent_report_is_context_and_not_a_server_verified_profile_contact():
    node = profile(external_reports=[{'evidence_level':'page_content','identifiers':[{'kind':'email','value':EMAIL}]}])
    assert target_affinity(node,Target(email=EMAIL))['weight'] < .2


def test_lookup_relation_does_not_claim_email_was_publicly_declared():
    google = entity(kind='google_account', metadata={'technique':'ghunt_people_profile','account_exists':True,'queried_email':EMAIL})
    email = entity(EMAIL,kind='email')
    relationships = detect_relationships(google,email)
    assert relationships[0][0] == 'email_lookup_association'
    assert relationships[0][2]['semantics'] == 'observed_relation_not_ownership'


def test_youtube_channel_ids_keep_case_in_deduplication_and_profile_links():
    from app.engine.persistence import finding_dedupe_key
    from app.tools.base import ToolFinding
    upper = 'https://youtube.com/channel/UC01234567890123456789AB'
    lower = 'https://youtube.com/channel/UC01234567890123456789ab'
    assert finding_dedupe_key(ToolFinding(entity_type='social_account',value=upper)) != finding_dedupe_key(ToolFinding(entity_type='social_account',value=lower))
    assert detect_relationships(profile(linked_profiles=[upper]),entity(lower)) == []


@pytest.mark.asyncio
async def test_large_name_neighborhood_keeps_anchor_without_transfer_or_identity_merging():
    anchor = profile(emails=[EMAIL],name='Observed Person')
    neighbors = [profile(name='Observed Person') for _ in range(30)]
    _,groups,affinities = await project_evidence(uuid.uuid4(),[anchor,*neighbors],Target(email=EMAIL))
    assert len(groups) == 31
    assert all(affinities[str(node.id)]['weight'] == 0 for node in neighbors)
    assert all(affinities[str(node.id)].get('placement_parent_id') == str(anchor.id) for node in neighbors)


def test_even_multiple_contacts_and_full_name_never_produce_identity_probability():
    node = profile(emails=[EMAIL],phones=[PHONE],name='Ana Perez',username='audit')
    result = target_affinity(node,Target(email=EMAIL,phone=PHONE,full_name='Ana Perez',username='audit'))
    assert result['weight'] < 1 and result['ownership_status'] == 'unverified'
