"""One current, read-only evidence projection for graph, REST and MCP."""
from uuid import uuid5, NAMESPACE_URL

from app.identity.evidence import POLICY_VERSION, projection, target_affinity
from app.identity.resolver import correlation_resolver
from app.models.relationship import Relationship


async def project_evidence(investigation_id, entities, target, persisted=()):
    from app.engine.persistence import infer_relationships
    affinities = {str(entity.id): target_affinity(entity, target) for entity in entities}
    edges = []
    for a, b, kind, grouping, evidence in infer_relationships(entities,
            priorities={key: value['weight'] for key, value in affinities.items()}):
        identity = f'{investigation_id}:{a.id}:{b.id}:{kind}'
        edges.append(Relationship(id=uuid5(NAMESPACE_URL, identity), investigation_id=investigation_id,
            source_entity_id=a.id, target_entity_id=b.id, relation_type=kind,
            supports_group=grouping, evidence=evidence))
    ids = {str(e.id) for e in entities}
    for edge in persisted:
        data = edge.evidence or {}
        distance = data.get('hamming_distance')
        if (edge.relation_type == 'similar_avatar' and type(distance) is int and 0 <= distance <= 4
                and data.get('method') == 'dhash' and str(edge.source_entity_id) in ids and str(edge.target_entity_id) in ids):
            edges.append(edge)
    groups = await correlation_resolver.resolve_groups(investigation_id, entities, edges)
    affinities = projection(entities, target, edges, affinities)
    return edges, groups, affinities


def compact_projection(affinities, edges, limit=30):
    ranked = sorted(affinities.items(), key=lambda item: (-item[1]['weight'], item[0]))
    return {'policy_version': POLICY_VERSION, 'semantics': 'visual_priority_not_identity_probability',
        'ownership_asserted': False, 'total_candidates': len(ranked),
        'candidates': [{'entity_id': key, **value} for key, value in ranked[:limit]],
        'has_more_candidates': len(ranked) > limit, 'observed_relationships': len(edges)}
