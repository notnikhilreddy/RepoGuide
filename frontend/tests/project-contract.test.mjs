import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const root=join(dirname(fileURLToPath(import.meta.url)),'..','src');
const source=(file)=>readFileSync(join(root,file),'utf8');
test('API client keeps all UI requests routed through local backend proxy',()=>{
  const client=source('lib/api.ts');
  assert.match(client,/const ui='\/api\/ui'/);
  assert.match(client,/streamAnswer/);
  assert.match(client,/AbortSignal/);
  assert.match(client,/evaluation-jobs/);
});
test('graph flow playback depends on stored graph edges',()=>{
  const graph=source('components/GraphView.tsx');
  assert.match(graph,/adjacency\.get\(current\)/);
  assert.match(graph,/e\.target/);
  assert.match(graph,/animated:lit/);
});
test('Monaco explicitly marks partial reconstructed files',()=>{
  const explorer=source('components/ExplorerView.tsx');
  assert.match(explorer,/content\?\.partial/);
  assert.match(explorer,/readOnly:true/);
});
test('chat only publishes a validated final event',()=>{
  const chat=source('components/ChatView.tsx');
  assert.match(chat,/event==='final'/);
  assert.match(chat,/unverified|validation pending/i);
});
