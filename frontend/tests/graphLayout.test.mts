import assert from 'node:assert/strict';
import test from 'node:test';
import { layoutDigitalMap } from '../src/lib/graphLayout.ts';
import { isProvenanceEdge, getFriendlyRelationLabel } from '../src/lib/graphSemantics.ts';

const radius = (point: {x:number,y:number}) => Math.hypot(point.x,point.y);

test('direct contact evidence stays nearer the root than contextual or absent evidence', () => {
  const items = [{id:'email',proximity:.88},{id:'name',proximity:.12},{id:'alias',proximity:0}];
  const result = layoutDigitalMap('root',items,[]);
  assert.ok(radius(result.positions.get('email')!) < radius(result.positions.get('name')!));
  assert.ok(radius(result.positions.get('name')!) < radius(result.positions.get('alias')!));
  assert.deepEqual(layoutDigitalMap('root',items,[]),result);
});

test('a contextual satellite stays near its parent without changing its direct target weight', () => {
  const items = [{id:'contact',proximity:.82},{id:'neighbor',proximity:0,parentId:'contact'}, {id:'unrelated',proximity:0}];
  const layout = layoutDigitalMap('root',items,[{source:'contact',target:'neighbor',relationType:'same_name',weight:.12}]);
  const contact = layout.positions.get('contact')!;
  const neighbor = layout.positions.get('neighbor')!;
  const other = layout.positions.get('unrelated')!;
  assert.ok(Math.hypot(contact.x-neighbor.x,contact.y-neighbor.y)<300);
  assert.ok(Math.hypot(contact.x-other.x,contact.y-other.y)>300);
  assert.equal(items[1].proximity,0);
  assert.ok(radius(neighbor)>radius(contact));
});

test('malformed or missing parents cannot displace the fixed root or produce NaN', () => {
  const layout = layoutDigitalMap('root',[{id:'a',parentId:'missing',proximity:0},{id:'b',proximity:.5}],[]);
  assert.deepEqual(layout.positions.get('root'),{x:0,y:0});
  for (const point of layout.positions.values()) assert.ok(Number.isFinite(point.x)&&Number.isFinite(point.y));
});

test('target contact evidence remains visible when derivation edges are hidden', () => {
  assert.equal(isProvenanceEdge({id:'source-a',relation_type:'target_email_match'} as Parameters<typeof isProvenanceEdge>[0]),false);
  assert.equal(isProvenanceEdge({id:'source-a',relation_type:'discovered_from'} as Parameters<typeof isProvenanceEdge>[0]),true);
  assert.equal(isProvenanceEdge({id:'rel-a',relation_type:'same_name'} as Parameters<typeof isProvenanceEdge>[0]),false);
  assert.match(getFriendlyRelationLabel('shares_email_and_username'),/correo y alias/);
});
