import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';
import ts from 'typescript';
const root=join(dirname(fileURLToPath(import.meta.url)),'..','src');
const source=file=>readFileSync(join(root,file),'utf8');
async function moduleFrom(file){const {outputText}=ts.transpileModule(source(file),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});return import('data:text/javascript;base64,'+Buffer.from(outputText).toString('base64'))}

test('API client keeps requests on the configured backend and includes cancellation',()=>{const client=source('lib/api.ts');assert.match(client,/const ui='\/api\/ui'/);assert.match(client,/requireAuthHeaders/);assert.match(client,/\/cancel/);assert.match(client,/AbortSignal/)});
test('architecture groups real files and collapses repeated cross-module relationships',async()=>{const {localArchitecture}=await moduleFrom('lib/architecture.ts');const graph={nodes:[{id:'a',file_path:'api/main.py'},{id:'b',file_path:'data/store.py'}],edges:[{source:'a',target:'b',kind:'calls'},{source:'a',target:'b',kind:'calls'},{source:'a',target:'a',kind:'contains'}]};const files=[{path:'api/main.py'},{path:'data/store.py'}];const root=localArchitecture(graph,files,'');assert.equal(root.nodes.length,2);assert.deepEqual(root.edges,[{source:'api',target:'data',kind:'calls',count:2}]);const child=localArchitecture(graph,files,'api');assert.equal(child.nodes[0].kind,'file');assert.equal(child.nodes[0].preview_path,'api/main.py');assert.equal(child.edges.length,0)});
test('citation markers cover code and docs without rewriting source code or unknown labels',async()=>{const {citationMarkdown}=await moduleFrom('lib/citations.ts');const result=citationMarkdown({answer:'Code [S1], docs [D1], unknown [S99]. `array[S1]`\n```py\n[S1]\n```',sources:[{label:'S1'}],docs_sources:[{label:'D1'}]});assert.match(result,/\[S1\]\(#citation-S1\)/);assert.match(result,/\[D1\]\(#citation-D1\)/);assert.match(result,/unknown \[S99\]/);assert.match(result,/`array\[S1\]`/);assert.match(result,/```py\n\[S1\]\n```/)});
test('source URLs reject non-HTTPS schemes and embedded credentials',async()=>{const {safeSourceUrl}=await moduleFrom('lib/citations.ts');for(const value of ['javascript:alert(1)','file:///private/key','http://example.com','https://secret@example.com/file'])assert.equal(safeSourceUrl(value),undefined);assert.equal(safeSourceUrl('https://github.com/example/project/blob/abc/main.py#L1-L2'),'https://github.com/example/project/blob/abc/main.py#L1-L2')});
test('Monaco keeps reconstructed source marked partial and read only',()=>{const explorer=source('components/ExplorerView.tsx');assert.match(explorer,/content\?\.partial/);assert.match(explorer,/readOnly:true/)});
