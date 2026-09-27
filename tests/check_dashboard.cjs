/* No test dependencies: verify Python/JavaScript parity and UI state transitions. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const core = require(path.join(root, 'templates/dashboard_core.js'));
const data = JSON.parse(fs.readFileSync(path.join(root, 'outputs/dashboard_data.json'), 'utf8'));
const rows = core.unpack(data), cohort = rows.filter(core.isCohort);
assert.equal(rows.length,10500);assert.equal(cohort.length,1968);
const frequencies=core.frequencies(rows);
assert.equal(frequencies.length,52500);
assert.deepEqual(Object.keys(frequencies[0]),['sample','total_count','population','count','percentage']);
assert.equal(frequencies[0].total_count,93214);
assert.ok(Math.abs(frequencies[0].percentage-100*10908/93214)<1e-12);
for(const mode of ['mean','baseline','day7','day14']){
  const values=core.comparisonValues(cohort,mode);
  assert.equal(values.length,656);
  for(let i=0;i<5;i++){
    for(const response of ['yes','no']){
      const box=core.boxStats(values.filter(r=>r.response===response).map(r=>r.values[i]));
      const expected=data.statistics[mode][i][response==='yes'?'median_responders_pct':'median_nonresponders_pct'];
      assert.ok(Math.abs(box.median-expected)<1e-11,`${mode}/${i}/${response} Python/JS mismatch`);
    }
  }
}
assert.equal(core.comparisonValues(cohort,'samples').length,1968);
assert.equal(core.filterRows(rows,{project:'prj2',sample_type:'PBMC'}).length,0);
assert.equal(core.filterRows(rows,{response:'unknown'}).length,1422);
assert.equal(core.boxStats([]),null);
assert.equal(core.csv([{a:'a,b',b:2}],['a','b']),'a,b\r\n"a,b",2');
assert.equal(core.csv([{a:'=1+1'}],['a']),'a\r\n\'=1+1');
assert.equal(core.csv([{a:' =1+1'}],['a']),'a\r\n\' =1+1');
assert.equal(core.csv([{a:'\t@cmd'}],['a']),'a\r\n\'\t@cmd');
const baselineColumns=['sample','project','subject','condition','age','sex','treatment','response','sample_type','time_from_treatment_start'];
assert.equal(core.csv(cohort.filter(r=>r.time_from_treatment_start===0).slice(0,1),baselineColumns).split('\r\n')[0],baselineColumns.join(','));

// Minimal DOM harness checks initialization, event handlers, empty states, downloads,
// and the optional tool. This is NOT a browser layout/accessibility test.
class Element {
 constructor(id){this.id=id;this.value='';this.innerHTML='';this.textContent='';this.hidden=false;this.disabled=false;this.handlers={};this.attrs={};this.classList={toggle(){}};}
 addEventListener(name,fn){this.handlers[name]=fn;}
 setAttribute(k,v){this.attrs[k]=v;}
 removeAttribute(k){delete this.attrs[k];}
 click(){if(this.handlers.click)this.handlers.click();}
 remove(){}
}
const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
get('study-data').textContent=JSON.stringify(data);get('comparison-mode').value='mean';
const views=['overview','response','baseline'].map(v=>get('view-'+v));
const nav=['overview','response','baseline'].map(v=>{const el=new Element('nav-'+v);el.dataset={view:v};return el;});
let registered,downloads=0;
const document={getElementById:get,querySelectorAll:s=>s==='.view'?views:nav,createElement:()=>{const el=new Element('a');el.click=()=>downloads++;return el;},body:{appendChild(){}},modelContext:{registerTool:t=>{registered=t;}}};
const context={document,ImmuneCore:core,window:{addEventListener(){}},Blob,URL,AbortController,setTimeout:fn=>fn(),console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'templates/dashboard_ui.js'),'utf8'),context);
assert.match(get('response-result').innerHTML,/No statistically significant/);
assert.match(get('response-result').innerHTML,/CD4 T cells/);
assert.match(get('response-kpis').innerHTML,/331 responders/);
assert.match(get('baseline-kpis').innerHTML,/656/);
assert.equal((get('boxplots').innerHTML.match(/<svg /g)||[]).length,5);
assert.match(get('stats-table').innerHTML,/0.0621/);
get('comparison-mode').value='samples';get('comparison-mode').handlers.change();
assert.equal(get('statistics-panel').hidden,true);assert.equal(get('download-stats').disabled,true);
get('comparison-mode').value='baseline';get('comparison-mode').handlers.change();
assert.equal(get('statistics-panel').hidden,false);assert.match(get('stats-table').innerHTML,/1.0000/);
get('download-stats').click();get('download-baseline').click();get('download-summary').click();get('download-baseline-summary').click();assert.equal(downloads,4);
assert.match(get('baseline-missing').textContent,/response 0 subjects · sex 0 subjects/);
get('filter-project').value='prj2';get('filter-sample_type').value='PBMC';get('filter-project').handlers.change();
assert.match(get('summary-count').textContent,/0 matching/);assert.equal(get('download-summary').disabled,true);
get('reset-filters').click();assert.match(get('summary-count').textContent,/52,500/);
get('sample-search').value='sample00000';get('sample-search').handlers.input();assert.match(get('summary-count').textContent,/of 5 rows/);
assert.equal(registered.name,'configure_immune_analysis_view');
assert.equal(registered.execute({section:'response',comparison:'mean'}).comparison,'mean');
assert.throws(()=>registered.execute({section:'response',comparison:'invalid'}));
assert.throws(()=>registered.execute({section:'baseline',comparison:'mean'}));
assert.equal(get('comparison-mode').value,'mean');
const html=fs.readFileSync(path.join(root,'dist/index.html'),'utf8');
assert.ok(!html.includes('__DATA_JSON__'));assert.ok(!html.includes('__CORE_JS__'));assert.ok(!html.includes('__UI_JS__'));
assert.ok(!/<script[^>]+src=/.test(html),'Offline dashboard must not require script downloads');
console.log('PASS: data/median parity, five charts, all response modes, filters, empty state, pagination data, CSV actions, and optional tool state checks.');
