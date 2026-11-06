// Read-only source browsing needs highlighting and editor navigation, not five
// language servers. Keep the editor worker and all assets on the same origin.
import {loader} from '@monaco-editor/react';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api';
import 'monaco-editor/esm/vs/editor/contrib/find/browser/findController.js';
import 'monaco-editor/esm/vs/editor/contrib/folding/browser/folding.js';
import 'monaco-editor/esm/vs/editor/contrib/bracketMatching/browser/bracketMatching.js';
import 'monaco-editor/esm/vs/editor/contrib/clipboard/browser/clipboard.js';
import 'monaco-editor/esm/vs/editor/contrib/contextmenu/browser/contextmenu.js';
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/ini/ini.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/sql/sql.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/css/css.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/html/html.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/shell/shell.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/go/go.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/rust/rust.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/java/java.contribution.js';
import 'monaco-editor/esm/vs/basic-languages/hcl/hcl.contribution.js';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';

monaco.languages.register({id:'json',extensions:['.json']});
monaco.languages.setMonarchTokensProvider('json',{tokenizer:{root:[[/"(?:[^"\\]|\\.)*"(?=\s*:)/,'string.key.json'],[/"(?:[^"\\]|\\.)*"/,'string.value.json'],[/-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/,'number'],[/\b(?:true|false|null)\b/,'keyword'],[/[{}[\],:]/,'delimiter']]}});
(self as unknown as {MonacoEnvironment:monaco.Environment}).MonacoEnvironment={getWorker(){return new EditorWorker()}};
loader.config({monaco});
