'use strict';
const payload = JSON.parse(document.getElementById('study-data').textContent);
const core = globalThis.ImmuneCore;
const allRows = core.unpack(payload), cohort = allRows.filter(core.isCohort);
const baseline = cohort.filter(r => r.time_from_treatment_start === 0);
const popLabels = payload.labels;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, digits = 0) => v == null ? '—' : Number(v).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const pFmt = v => v < 0.0001 ? v.toExponential(2) : v.toFixed(4);
function kpi(label, value, foot) {return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="foot">${esc(foot)}</div></div>`;}
function table(headers, rows, numeric = []) {return `<table><thead><tr>${headers.map((h,i)=>`<th scope="col" class="${numeric.includes(i)?'num':''}">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map(row=>`<tr>${row.map((c,i)=>`<td class="${numeric.includes(i)?'num':''}">${esc(c)}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${headers.length}" class="empty">No matching records. Adjust the filters.</td></tr>`}</tbody></table>`;}
function download(name, rows, columns) {
  const blob = new Blob([core.csv(rows, columns)], {type:'text/csv;charset=utf-8;'}), url = URL.createObjectURL(blob), a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
let currentView = 'response';
function showView(view) {
  if (!['overview','response','baseline'].includes(view)) throw new Error('Unknown dashboard section.');
  currentView = view;
  document.querySelectorAll('.view').forEach(el => el.hidden = el.id !== 'view-' + view);
  document.querySelectorAll('[data-view]').forEach(b => {const active = b.dataset.view === view; b.classList.toggle('active',active); if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  if(view==='overview') renderOverview();
}
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>showView(b.dataset.view)));

// Response comparison: every inferential view corresponds to Python-generated tests.
function chart(values, index) {
  const maxValue = Math.max(...values.map(r=>r.values[index]), 1), ymax = Math.ceil(maxValue/5)*5 + 5;
  const y = n => 228 - n/ymax*182;
  let svg = `<svg viewBox="0 0 310 287" role="img" aria-label="${esc(popLabels[core.populations[index]])} frequency boxplots by response"><title>${esc(popLabels[core.populations[index]])}: responder and non-responder frequency distributions</title>`;
  for(let t=0;t<=4;t++){const v=t*ymax/4;svg+=`<line x1="42" y1="${y(v)}" x2="295" y2="${y(v)}" stroke="#000" stroke-width=".5" stroke-dasharray="1 3"/><text x="35" y="${y(v)+4}" text-anchor="end" fill="#000" font-size="11">${fmt(v,1)}</text>`;}
  svg+='<text x="12" y="26" fill="#000" font-size="11">%</text>';
  ['no','yes'].forEach((response,g)=>{
    const group=values.filter(r=>r.response===response), s=core.boxStats(group.map(r=>r.values[index])), x=g?225:112;
    const dash=g?'':' stroke-dasharray="4 3"', dot=g?'fill="#000"':'fill="#fff" stroke="#000" stroke-width=".6"';
    if(!s)return;
    group.forEach((r,i)=>{const offset=(((i*73+index*31)%101)/100-.5)*58;svg+=`<circle cx="${x+offset}" cy="${y(r.values[index])}" r="1.5" ${dot}><title>${esc(r.id)} · ${response==='yes'?'Responder':'Non-responder'}: ${fmt(r.values[index],3)}%</title></circle>`;});
    const boxH=Math.max(.5,y(s.q1)-y(s.q3));
    svg+=`<g fill="none" stroke="#fff" stroke-width="5"><rect x="${x-24}" y="${y(s.q3)}" width="48" height="${boxH}"/><line x1="${x-24}" y1="${y(s.median)}" x2="${x+24}" y2="${y(s.median)}" stroke-width="7"/><line x1="${x}" y1="${y(s.low)}" x2="${x}" y2="${y(s.q1)}"/><line x1="${x}" y1="${y(s.q3)}" x2="${x}" y2="${y(s.high)}"/></g>`;
    svg+=`<g fill="none" stroke="#000"><title>n=${s.n}; median=${fmt(s.median,3)}%; Q1=${fmt(s.q1,3)}%; Q3=${fmt(s.q3,3)}%; whiskers=${fmt(s.low,3)}–${fmt(s.high,3)}%</title><line x1="${x}" y1="${y(s.low)}" x2="${x}" y2="${y(s.q1)}" stroke-width="1.5"${dash}/><line x1="${x}" y1="${y(s.q3)}" x2="${x}" y2="${y(s.high)}" stroke-width="1.5"${dash}/><path d="M${x-12},${y(s.low)}h24 M${x-12},${y(s.high)}h24" stroke-width="1.5"/><rect x="${x-24}" y="${y(s.q3)}" width="48" height="${boxH}" stroke-width="1.5"${dash}/><line x1="${x-24}" y1="${y(s.median)}" x2="${x+24}" y2="${y(s.median)}" stroke-width="3"/></g><text x="${x}" y="251" text-anchor="middle" font-size="11" fill="#000">${g?'Responders':'Non-responders'}</text><text x="${x}" y="270" text-anchor="middle" font-size="11" fill="#000">n = ${fmt(s.n)}</text>`;
  });
  return svg+'</svg>';
}
function renderComparison() {
  const mode=$('comparison-mode').value, values=core.comparisonValues(cohort,mode), stats=payload.statistics[mode];
  const yes=values.filter(r=>r.response==='yes').length, no=values.length-yes, samples=mode==='samples';
  const units=samples?'Samples':'Subjects', a=payload.audit;
  $('response-kpis').innerHTML=kpi('Eligible samples',fmt(mode==='mean'||samples?a.cohort_samples:values.length),mode==='mean'||samples?'Across days 0, 7, and 14':'At the selected visit')+kpi('Independent subjects',fmt(a.cohort_subjects),`${fmt(a.responder_subjects)} responders · ${fmt(a.nonresponder_subjects)} non-responders`)+kpi(`${units} · responders`,fmt(yes),samples?'Repeated visits included':'One value per population')+kpi(`${units} · non-responders`,fmt(no),samples?'Repeated visits included':'One value per population');
  const significant=stats?stats.filter(r=>r.significant_holm_0_05):[];
  const main=stats?(significant.length?`${significant.length} population${significant.length>1?'s':''} with adjusted p ≤ 0.05`:'No statistically significant differences after correction'):'All-sample distributions are descriptive';
  let detail;
  if(samples){
    detail=`These ${fmt(a.cohort_samples)} samples include three visits per subject. Select subject averages or a single visit for independent-subject statistical tests.`;
  }else if(mode==='mean'){
    const top=stats.slice().sort((x,y)=>x.p_holm-y.p_holm||x.p_value-y.p_value)[0];
    detail=`${popLabels[top.population]}: raw p = ${pFmt(top.p_value)}, Holm-adjusted p = ${pFmt(top.p_holm)}. The evidence ${top.significant_holm_0_05?'meets':'does not meet'} the 0.05 threshold.`;
  }else{
    detail=`Exploratory ${mode==='baseline'?'baseline':mode==='day7'?'day 7':'day 14'} comparison. Holm correction is applied to five populations within this view; results are not adjusted across all visits.`;
  }
  $('response-result').innerHTML=`<div class="symbol">${samples?'i':'≈'}</div><div><strong>${esc(main)}</strong><p>${esc(detail)}</p></div>`;
  $('comparison-caption').textContent=mode==='mean'?'One point per subject · mean percentage across three visits':samples?'One point per sample · repeated observations from each subject':`One point per subject · ${mode==='baseline'?'day 0':mode==='day7'?'day 7':'day 14'}`;
  $('boxplots').innerHTML=core.populations.map((p,i)=>`<div class="chart-card"><h3>${esc(popLabels[p])}</h3><div class="chart-meta">${stats?`Holm p = ${pFmt(stats[i].p_holm)}`:'Descriptive sample distribution'}</div>${chart(values,i)}</div>`).join('')+`<div class="method-card"><h3>${samples?'Repeated visits':'Independent subjects'}</h3><p>${samples?'Multiple samples belong to the same person. This view describes the observed samples; it does not treat each visit as an independent patient.':'Each subject contributes one value per population. This prevents repeated visits from artificially inflating the sample size.'}</p><p>${mode==='mean'?'Averages include post-treatment information and are not a baseline prediction model.':'Day-specific comparisons describe associations, not treatment effects.'}</p><p class="muted">The population axes use different scales. Compare the two response groups within each panel.</p></div>`;
  $('statistics-panel').hidden=samples;
  $('download-stats').disabled=samples;
  if(stats){
    $('stats-caption').textContent=`Two-sided Mann–Whitney U · ${yes} responders vs. ${no} non-responders · ${mode==='mean'?'subject averages':mode==='baseline'?'baseline':mode==='day7'?'day 7':'day 14'}`;
    $('stats-table').innerHTML=table(['Population','Responder median %','Non-responder median %','U statistic','Raw p','Holm p','Rank-biserial','Result'],stats.map(s=>[popLabels[s.population],fmt(s.median_responders_pct,3),fmt(s.median_nonresponders_pct,3),fmt(s.u_statistic_responders),pFmt(s.p_value),pFmt(s.p_holm),fmt(s.rank_biserial,4),s.significant_holm_0_05?'Significant':'Not significant']),[1,2,3,4,5,6]);
  }
}
$('comparison-mode').addEventListener('change',renderComparison);
$('download-stats').addEventListener('click',()=>{const mode=$('comparison-mode').value,rows=payload.statistics[mode];if(rows)download(`statistics_${mode}.csv`,rows,Object.keys(rows[0]));});

// Overview controls only filter Part 2; no implicit changes to the inferential cohort.
const filterDefs=[['project','Project'],['condition','Condition'],['treatment','Treatment'],['sample_type','Sample type'],['response','Response'],['time_from_treatment_start','Visit day']];
let overviewPage=0, visibleSummary=[]; const pageSize=15;
$('overview-controls').innerHTML=filterDefs.map(([key,label])=>`<label class="control">${label}<select id="filter-${key}"><option value="">All</option>${[...new Set(allRows.map(r=>r[key]??'unknown'))].sort((a,b)=>typeof a==='number'?a-b:String(a).localeCompare(String(b))).map(v=>`<option value="${esc(v)}">${esc(v==='unknown'?'Unknown / not recorded':v)}</option>`).join('')}</select></label>`).join('')+'<button id="reset-filters">Reset</button>';
filterDefs.forEach(([k])=>$('filter-'+k).addEventListener('change',()=>{overviewPage=0;renderOverview();}));
$('reset-filters').addEventListener('click',()=>{filterDefs.forEach(([k])=>$('filter-'+k).value='');$('sample-search').value='';overviewPage=0;renderOverview();});
$('sample-search').addEventListener('input',()=>{overviewPage=0;renderOverview();});
function overviewRows(){const filters=Object.fromEntries(filterDefs.map(([k])=>[k,$('filter-'+k).value])),query=$('sample-search').value.toLowerCase().trim();return core.filterRows(allRows,filters).filter(r=>!query||r.sample.toLowerCase().includes(query));}
function renderOverview(){
  const rows=overviewRows(),nonzero=rows.filter(r=>r.total_count>0); visibleSummary=core.frequencies(rows);
  $('overview-kpis').innerHTML=kpi('Samples',fmt(rows.length),'Filtered sample IDs')+kpi('Subjects',fmt(new Set(rows.map(r=>r.subject)).size),'Distinct subject IDs')+kpi('Total measured cells',fmt(rows.reduce((n,r)=>n+r.total_count,0)),'Sum of the five populations')+kpi('Summary rows',fmt(visibleSummary.length),'Five populations per sample');
  const means=core.populations.map((p,i)=>nonzero.length?nonzero.reduce((n,r)=>n+r.values[i],0)/nonzero.length:0);
  $('composition-chart').innerHTML=nonzero.length?`<div role="img" aria-label="Mean population composition">${means.map((v,i)=>`<div class="bar-label"><span>${esc(popLabels[core.populations[i]])}</span><strong>${fmt(v,2)}%</strong></div><div class="bar-track" title="${esc(popLabels[core.populations[i]])}: ${fmt(v,3)}%"><div class="bar-fill" style="width:${v}%"></div></div>`).join('')}</div>`:'<div class="empty">No samples with a positive total match these filters.</div>';
  overviewPage=Math.min(overviewPage,Math.max(0,Math.ceil(visibleSummary.length/pageSize)-1));const start=overviewPage*pageSize;
  $('summary-table').innerHTML=table(['sample','total_count','population','count','percentage'],visibleSummary.slice(start,start+pageSize).map(r=>[r.sample,fmt(r.total_count),r.population,fmt(r.count),r.percentage===null?'Undefined':fmt(r.percentage,5)]),[1,3,4]);
  $('summary-count').textContent=visibleSummary.length?`Showing ${fmt(start+1)}–${fmt(Math.min(start+pageSize,visibleSummary.length))} of ${fmt(visibleSummary.length)} rows`:'0 matching rows';
  $('page-number').textContent=`${overviewPage+1} / ${Math.max(1,Math.ceil(visibleSummary.length/pageSize))}`;
  $('page-prev').disabled=overviewPage===0;$('page-next').disabled=start+pageSize>=visibleSummary.length;
  $('download-summary').disabled=!visibleSummary.length;
}
$('page-prev').addEventListener('click',()=>{overviewPage--;renderOverview();});$('page-next').addEventListener('click',()=>{overviewPage++;renderOverview();});
$('download-summary').addEventListener('click',()=>download('sample_frequencies.csv',visibleSummary,['sample','total_count','population','count','percentage']));

function renderBaseline(){
 const b=payload.baseline;
 $('baseline-kpis').innerHTML=kpi('Baseline samples',fmt(baseline.length),'Day 0 only')+kpi('Distinct subjects',fmt(new Set(baseline.map(r=>r.subject)).size),'One baseline sample each')+kpi('Responders',fmt(b.response.find(r=>r.response==='yes')?.subject_count??0),'Distinct subjects')+kpi('Non-responders',fmt(b.response.find(r=>r.response==='no')?.subject_count??0),'Distinct subjects');
 const max=Math.max(...b.projects.map(r=>r.sample_count),1);
 $('project-bars').innerHTML=b.projects.map(r=>`<div class="bar-label"><span>${esc(r.project)}</span><strong>${fmt(r.sample_count)}</strong></div><div class="bar-track"><div class="bar-fill" style="width:${100*r.sample_count/max}%"></div></div>`).join('');
 $('project-table').innerHTML=table(['Project','Samples'],b.projects.map(r=>[r.project,fmt(r.sample_count)]),[1]);
 $('baseline-breakdowns').innerHTML='<h3>Response</h3>'+table(['Response','Subjects'],b.response.map(r=>[r.response==='yes'?'Responders':r.response==='no'?'Non-responders':'Unknown',fmt(r.subject_count)]),[1])+'<h3 style="margin-top:26px">Recorded sex</h3>'+table(['Sex','Subjects'],b.sex.map(r=>[r.sex==='F'?'Female (F)':r.sex==='M'?'Male (M)':r.sex,fmt(r.subject_count)]),[1]);
 const missing=Object.fromEntries((b.missing||[]).map(r=>[r.field,r.missing_subjects]));
 $('baseline-missing').textContent=`Missing values: response ${fmt(missing.response??0)} subjects · sex ${fmt(missing.sex??0)} subjects. Missing values are shown as Unknown, not dropped.`;
 $('baseline-table').innerHTML=table(['sample','project','subject','response','sex','day'],baseline.slice(0,20).map(r=>[r.sample,r.project,r.subject,r.response,r.sex,r.time_from_treatment_start]),[5]);
}
const baselineExportColumns=['sample','project','subject','condition','age','sex','treatment','response','sample_type','time_from_treatment_start'];
$('download-baseline').addEventListener('click',()=>download('baseline_samples.csv',baseline,baselineExportColumns));
function baselineSummaryRows(){
 const b=payload.baseline;
 return [...b.projects.map(r=>({table:'samples_by_project',group:r.project,count:r.sample_count})),
  ...b.response.map(r=>({table:'subjects_by_response',group:r.response,count:r.subject_count})),
  ...b.sex.map(r=>({table:'subjects_by_sex',group:r.sex,count:r.subject_count})),
  ...(b.missing||[]).map(r=>({table:'subjects_missing',group:r.field,count:r.missing_subjects}))];
}
$('download-baseline-summary').addEventListener('click',()=>download('baseline_summary.csv',baselineSummaryRows(),['table','group','count']));
renderComparison();renderBaseline();renderOverview();

// Optional browser-agent entry point: same controls, state, and results as the UI.
if(document.modelContext?.registerTool){
 const lifecycle=new AbortController();
 const tool={name:'configure_immune_analysis_view',title:'Configure immune analysis view',description:'Open a section and optionally select a response comparison. Updates dashboard controls; does not alter the dataset.',inputSchema:{type:'object',properties:{section:{type:'string',enum:['overview','response','baseline']},comparison:{type:'string',enum:['mean','baseline','day7','day14','samples']}},required:['section'],additionalProperties:false},annotations:{readOnlyHint:false},execute(input){if(!input||!['overview','response','baseline'].includes(input.section)||Object.keys(input).some(k=>!['section','comparison'].includes(k))||(input.comparison!==undefined&&!['mean','baseline','day7','day14','samples'].includes(input.comparison)))throw new Error('Invalid section or comparison.');if(input.comparison&&input.section!=='response')throw new Error('Comparison requires the response section.');if(input.comparison){$('comparison-mode').value=input.comparison;renderComparison();}showView(input.section);return {section:currentView,comparison:$('comparison-mode').value,cohort_subjects:payload.audit.cohort_subjects};}};
 try{Promise.resolve(document.modelContext.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch(error){/* Optional API; dashboard remains functional. */}
 window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
