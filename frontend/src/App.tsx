import React, {useEffect, useRef, useState} from 'react';
import {activeCases,businessImpact,compareScenarios,getProcess,postProcess,runScenario,trainModel,uploadDataset} from './api';
import type {
  ActiveCaseResponse,
  BusinessImpact as BusinessImpactResult,
  ModelMetrics,
  ProcessGraph,
  Scenario,
  SimulationResult,
  Variant,
} from './types';
import ProcessMap from './components/ProcessMap';
import VariantCards from './components/VariantCards';
import ScenarioBuilder from './components/ScenarioBuilder';
import {DataTable,Kpi,Kpis,Notice} from './components/Common';

const pages=['Overview','Process Map','Variants','Bottlenecks & Rework','SLA & Conformance','Active Case Risk','Transformation Lab','Scenario Comparison','Business Impact','Model Evaluation','Data Quality','Assumptions / Limitations'];
const fmt=(value:unknown)=>typeof value==='number'?value.toLocaleString(undefined,{maximumFractionDigits:3}):String(value??'—');

interface OverviewData {
  case_count:number; activity_count:number; variant_count:number; median_cycle_hours:number; p95_cycle_hours:number;
  sla_compliance:number; rework_rate:number; top_bottleneck?:{activity:string;median_inter_event_delay_hours:number}|null;
}
interface BottleneckRow extends Record<string,unknown> { activity:string }
interface BottleneckReworkData { bottlenecks:BottleneckRow[]; rework:Record<string,unknown> }
interface RecommendationOption {
  recommendation:string; activity:string;
  why_this?:{cases_affected_pct?:number};
  simulated?:{fidelity_status?:string;median_cycle_reduction_pct?:number;sla_compliance_delta_pp?:number};
}
interface ComparisonData { results:SimulationResult[]; comparison_basis?:string }

type SetDashboardData=(value:unknown)=>void;

export default function App(){
  const [page,setPage]=useState('Overview');
  const [dataset,setDataset]=useState<number|null>(null);
  const [status,setStatus]=useState('Import a CSV/JSON event log to begin.');
  const [data,setData]=useState<unknown>(null);
  const [graph,setGraph]=useState<ProcessGraph|null>(null);
  const [bottlenecks,setBottlenecks]=useState<string[]>([]);
  const [saved,setSaved]=useState<Scenario[]>([]);
  const [sim,setSim]=useState<SimulationResult|null>(null);
  const [model,setModel]=useState<ModelMetrics|null>(null);
  const [impact,setImpact]=useState<BusinessImpactResult|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const pageRequest=useRef(0);
  const activities=graph?.activities.map(activity=>activity.activity)??[];

  async function load<T>(fn:()=>Promise<T>){
    setBusy(true);setError('');
    try{return await fn();}
    catch(caught){setError(caught instanceof Error?caught.message:String(caught));return undefined;}
    finally{setBusy(false);}
  }
  async function upload(file:File){
    const imported=await load(()=>uploadDataset(file));if(!imported)return;
    pageRequest.current+=1;setDataset(imported.id);setStatus(`Dataset ${imported.id} imported and validated.`);setData(null);
    const nextGraph=await getProcess<ProcessGraph>(imported.id,'graph');setGraph(nextGraph);setPage('Overview');
  }

  useEffect(()=>{
    if(dataset===null)return;
    const currentDatasetId: number = dataset;
    const requestId=++pageRequest.current;
    let cancelled=false;
    setData(null);
    setError('');

    const isCurrent=()=>!cancelled&&pageRequest.current===requestId;
    async function fetchPage(datasetId: number){
      const requiresRequest=['Overview','Process Map','Variants','Data Quality','Bottlenecks & Rework','Active Case Risk'].includes(page);
      if(!requiresRequest){if(isCurrent())setBusy(false);return;}
      setBusy(true);
      try{
        if(page==='Overview'){
          const result=await getProcess<OverviewData>(datasetId,'overview');if(isCurrent())setData(result);return;
        }
        if(page==='Process Map'){
          const [nextGraph,rows]=await Promise.all([
            getProcess<ProcessGraph>(datasetId,'graph'),
            getProcess<BottleneckRow[]>(datasetId,'bottlenecks'),
          ]);
          if(isCurrent()){
            setGraph(nextGraph);
            setBottlenecks(rows.slice(0,3).map(row=>row.activity));
            setData(nextGraph);
          }
          return;
        }
        if(page==='Variants'){
          const result=await getProcess<Variant[]>(datasetId,'variants');if(isCurrent())setData(result);return;
        }
        if(page==='Data Quality'){
          const result=await getProcess<Record<string,unknown>>(datasetId,'quality');if(isCurrent())setData(result);return;
        }
        if(page==='Bottlenecks & Rework'){
          const [rows,rework]=await Promise.all([
            getProcess<BottleneckRow[]>(datasetId,'bottlenecks'),
            getProcess<Record<string,unknown>>(datasetId,'rework'),
          ]);
          if(isCurrent()){
            setBottlenecks(rows.slice(0,3).map(row=>row.activity));
            setData({bottlenecks:rows,rework} satisfies BottleneckReworkData);
          }
          return;
        }
        if(page==='Active Case Risk'){
          const result=await activeCases(datasetId);if(isCurrent())setData(result);
        }
      }catch(caught){
        if(isCurrent())setError(caught instanceof Error?caught.message:String(caught));
      }finally{
        if(isCurrent())setBusy(false);
      }
    }
    void fetchPage(currentDatasetId);
    return()=>{cancelled=true;};
  },[page,dataset]);

  async function train(){
    if(!dataset)return;
    const result=await load(()=>trainModel(dataset));if(!result)return;
    setModel(result);setStatus(`Model ${result.version} trained and persisted.`);
    if(page==='Active Case Risk'){
      const scored=await load(()=>activeCases(dataset));setData(scored??null);
    }else setData(result);
  }
  async function run(scenario:Scenario){if(!dataset)return;const result=await load(()=>runScenario(dataset,scenario));if(result){setSim(result);setData(result);setStatus(`${scenario.name}: paired counterfactual simulation complete.`);}}
  async function compare(){if(!dataset||saved.length===0)return;const result=await load(()=>compareScenarios(dataset,saved));if(result)setData(result);}
  function navigate(nextPage:string){pageRequest.current+=1;setData(null);setError('');setPage(nextPage);}

  return <div className="shell">
    <aside className="nav"><div className="brand">FLOWLENS<span>Counterfactual Process Twin</span></div>{pages.map(item=><button key={item} className={page===item?'active':''} onClick={()=>navigate(item)}>{item}</button>)}</aside>
    <main>
      <header><div><div className="eyebrow">OBSERVED → SIMULATED → PREDICTED → ESTIMATED</div><h1>{page}</h1><p>{status}</p></div><label className="upload">Import event log<input type="file" accept=".csv,.json" onChange={event=>event.target.files?.[0]&&void upload(event.target.files[0])}/></label></header>
      {error&&<Notice kind="warn">{error}</Notice>}{busy&&<div className="progress">Working…</div>}
      <section className="panel">{!dataset?<div className="empty"><strong>No dataset loaded</strong><span>Import a validated event log to activate the process twin.</span></div>:<Page page={page} data={data} graph={graph} bottlenecks={bottlenecks} activities={activities} train={train} model={model} run={run} sim={sim} saved={saved} setSaved={setSaved} compare={compare} setData={value=>setData(value)} dataset={dataset} impact={impact} setImpact={setImpact}/>}</section>
      <footer>SYNTHETIC examples are labeled. SIMULATED impact is not guaranteed. ESTIMATED business value requires explicit assumptions. PREDICTED risk comes from persisted models.</footer>
    </main>
  </div>;
}

interface PageProps {
  page:string; data:unknown; graph:ProcessGraph|null; bottlenecks:string[]; activities:string[];
  train:()=>Promise<void>; model:ModelMetrics|null; run:(scenario:Scenario)=>Promise<void>; sim:SimulationResult|null;
  saved:Scenario[]; setSaved:React.Dispatch<React.SetStateAction<Scenario[]>>; compare:()=>Promise<void>;
  setData:SetDashboardData; dataset:number; impact:BusinessImpactResult|null;
  setImpact:React.Dispatch<React.SetStateAction<BusinessImpactResult|null>>;
}
function Page({page,data,graph,bottlenecks,activities,train,model,run,sim,saved,setSaved,compare,setData,dataset,impact,setImpact}:PageProps){
  if(page==='Overview')return <Overview data={data as OverviewData|null}/>;
  if(page==='Process Map')return graph?<><Notice>{graph.terminology_note}</Notice><ProcessMap graph={graph} bottlenecks={bottlenecks}/></>:null;
  if(page==='Variants')return <VariantCards variants={(data??[]) as Variant[]}/>;
  if(page==='Bottlenecks & Rework')return <Bottlenecks data={data as BottleneckReworkData|null}/>;
  if(page==='SLA & Conformance')return <SlaConformance dataset={dataset} setData={setData} data={data}/>;
  if(page==='Active Case Risk')return <ActiveRisk data={data} train={train}/>;
  if(page==='Transformation Lab')return <><ScenarioBuilder activities={activities} onRun={scenario=>void run(scenario)} onSave={scenario=>setSaved(current=>[...current.filter(item=>item.name!==scenario.name),scenario])}/><RecommendationPanel dataset={dataset}/>{sim&&<SimulationView sim={sim}/>}</>;
  if(page==='Scenario Comparison')return <ScenarioComparison saved={saved} compare={compare} data={data as ComparisonData|null}/>;
  if(page==='Business Impact')return <BusinessImpact sim={sim} impact={impact} setImpact={value=>setImpact(value)} activities={activities}/>;
  if(page==='Model Evaluation')return <ModelEval data={model} train={train}/>;
  if(page==='Data Quality')return <ObjectGrid data={asRecord(data)}/>;
  return <Assumptions/>;
}

function Overview({data}:{data:OverviewData|null}){if(!data)return null;return <><Kpis><Kpi label="Cases" value={fmt(data.case_count)}/><Kpi label="Activities" value={fmt(data.activity_count)}/><Kpi label="Variants" value={fmt(data.variant_count)}/><Kpi label="Median cycle" value={`${fmt(data.median_cycle_hours)}h`}/><Kpi label="P95 cycle" value={`${fmt(data.p95_cycle_hours)}h`}/><Kpi label="SLA compliance" value={`${(data.sla_compliance*100).toFixed(1)}%`}/><Kpi label="Rework rate" value={`${(data.rework_rate*100).toFixed(1)}%`}/><Kpi label="Top bottleneck" value={data.top_bottleneck?.activity??'—'} note={data.top_bottleneck?`${data.top_bottleneck.median_inter_event_delay_hours}h median inter-event delay`:undefined}/></Kpis><Notice>Overview metrics are OBSERVED directly from the imported event log.</Notice></>}
function Bottlenecks({data}:{data:BottleneckReworkData|null}){if(!data)return null;return <div className="stack"><h2>Observed bottleneck evidence</h2><DataTable rows={data.bottlenecks} columns={['activity','timing_basis','cases_affected','percentage_cases','median_inter_event_delay_hours','p95_inter_event_delay_hours','median_wait_hours','median_processing_hours','contribution_to_total_cycle']}/><Notice>Completion-only logs support <b>observed inter-event delay</b>, not pure waiting/processing time.</Notice><h2>Rework / loops</h2><ObjectGrid data={data.rework}/></div>}
function SlaConformance({dataset,setData,data}:{dataset:number;setData:SetDashboardData;data:unknown}){const[process,setProcess]=useState(48),[activity,setActivity]=useState('Finance Review'),[activityHours,setActivityHours]=useState(12),[expected,setExpected]=useState('Request,Manager Approval,Finance Review,Purchase Order,Invoice,Payment');async function sla(){setData(await postProcess(dataset,'sla/rules',{rules:[{name:'Process SLA',scope:'process',threshold_hours:process,severity:'high'},{name:`${activity} SLA`,scope:'activity',activity,threshold_hours:activityHours,severity:'medium'}]}));}async function conf(){setData(await postProcess(dataset,'conformance',{expected:expected.split(',').map(item=>item.trim()).filter(Boolean),max_loops:1}));}return <div className="stack"><div className="form-grid"><label>Process SLA (h)<input type="number" value={process} onChange={event=>setProcess(+event.target.value)}/></label><label>Activity<input value={activity} onChange={event=>setActivity(event.target.value)}/></label><label>Activity SLA (h)<input type="number" value={activityHours} onChange={event=>setActivityHours(+event.target.value)}/></label></div><div className="row"><button className="primary" onClick={()=>void sla()}>Evaluate SLA rules</button></div><label>Expected process<input value={expected} onChange={event=>setExpected(event.target.value)}/></label><button onClick={()=>void conf()}>Run heuristic conformance</button>{data!=null&&<JsonPanel data={data}/>}</div>}
export function ActiveRisk({data,train}:{data:unknown;train:()=>Promise<void>}){const candidate=data!=null&&typeof data==='object'?data as Partial<ActiveCaseResponse>:null;if(!candidate||!Array.isArray(candidate.cases))return <button className="primary" onClick={()=>void train()}>Train & persist model first</button>;const response=candidate as ActiveCaseResponse;return <><Notice>PREDICTED SLA risk and remaining time from the persisted model. Historical snapshot cutoff: {response.cutoff||'—'}</Notice><div className="row"><button onClick={()=>void train()}>Retrain model</button></div><DataTable rows={response.cases as unknown as Record<string,unknown>[]} columns={['case_id','current_activity','elapsed_hours','activities_completed','rework_count','priority','breach_probability','expected_remaining_hours','predicted_completion_time','risk_level','model_version']}/></>}
function RecommendationPanel({dataset}:{dataset:number}){const[rows,setRows]=useState<RecommendationOption[]>([]),[loading,setLoading]=useState(false);async function load(){setLoading(true);try{setRows(await getProcess<RecommendationOption[]>(dataset,'recommendations'));}finally{setLoading(false);}}return <div className="stack"><div className="row"><h2>Evidence-derived options</h2><button onClick={()=>void load()}>{loading?'Evaluating…':'Generate & simulate options'}</button></div>{rows.map((row,index)=><article className="saved" key={`${row.recommendation}-${index}`}><div><strong>{index+1}. {row.recommendation}</strong><div className="muted">{row.activity} · affected {fmt(row.why_this?.cases_affected_pct)}% · fidelity {fmt(row.simulated?.fidelity_status)}</div></div><span>Median cycle Δ {fmt(row.simulated?.median_cycle_reduction_pct)}% · SLA Δ {fmt(row.simulated?.sla_compliance_delta_pp)}pp</span></article>)}</div>}

function SimulationView({sim}:{sim:SimulationResult}){const uncertainty=sim.uncertainty.cycle_time_reduction_pct;return <div className="stack"><Notice kind={sim.baseline_fidelity.status==='LOW'?'warn':'ok'}>Baseline fidelity: <b>{sim.baseline_fidelity.status}</b>{sim.baseline_fidelity.warning?` — ${sim.baseline_fidelity.warning}`:''}</Notice><Kpis><Kpi label="SIMULATED baseline median" value={`${fmt(sim.baseline.median_cycle_hours)}h`}/><Kpi label="SIMULATED scenario median" value={`${fmt(sim.proposed.median_cycle_hours)}h`}/><Kpi label="SIMULATED reduction" value={`${fmt(sim.simulated_impact.median_cycle_reduction_pct)}%`}/><Kpi label="SIMULATED SLA Δ" value={`${fmt(sim.simulated_impact.sla_compliance_delta_pp)} pp`}/><Kpi label="SIMULATED 30-day completion volume" value={fmt(sim.proposed.simulated_throughput_cases_per_30d)}/><Kpi label="Uncertainty P10" value={`${fmt(uncertainty.p10)}%`}/><Kpi label="Uncertainty P90" value={`${fmt(uncertainty.p90)}%`}/></Kpis><Notice>Completion volume is counted over a fixed {fmt(sim.throughput_methodology.simulation_horizon_hours)}h horizon under calibrated historical arrivals ({fmt(sim.throughput_methodology.historical_arrival_rate_cases_per_30d)} cases/30d). It is not a maximum system-capacity claim and is independent of analysis cohort size.</Notice><small>{sim.disclaimer}</small></div>}
export function ScenarioComparison({saved,compare,data}:{saved:Scenario[];compare:()=>Promise<void>;data:ComparisonData|null}){return <div className="stack"><div className="row"><b>Saved scenarios: {saved.length}</b><button className="primary" disabled={!saved.length} onClick={()=>void compare()}>Compare saved scenarios</button></div>{saved.map((scenario,index)=><div className="saved" key={`${scenario.name}-${index}`}><strong>{scenario.name}</strong><span>{scenario.actions.length} actions · {scenario.runs} paired runs · SLA {scenario.sla_hours}h</span></div>)}{data?.results&&<div className="comparison">{data.results.map((result,index)=><article key={`${result.scenario.name}-${index}`}><h3>{result.scenario.name}</h3><Kpi label="SIMULATED median cycle" value={`${result.proposed.median_cycle_hours}h`}/><Kpi label="SIMULATED P95" value={`${result.proposed.p95_cycle_hours}h`}/><Kpi label="SIMULATED SLA" value={`${(result.proposed.sla_compliance*100).toFixed(1)}%`}/><Kpi label="SIMULATED 30-day completion volume" value={result.proposed.simulated_throughput_cases_per_30d}/><Kpi label="P10–P90 cycle reduction" value={`${result.uncertainty.cycle_time_reduction_pct.p10}% – ${result.uncertainty.cycle_time_reduction_pct.p90}%`}/></article>)}</div>}</div>}
function BusinessImpact({sim,impact,setImpact,activities}:{sim:SimulationResult|null;impact:BusinessImpactResult|null;setImpact:(value:BusinessImpactResult)=>void;activities:string[]}){const[cases,setCases]=useState(1000),[labor,setLabor]=useState(30),[breach,setBreach]=useState(0),[rework,setRework]=useState(0),[automationCost,setAutomationCost]=useState(0),[implementationCost,setImplementationCost]=useState(0),[faster,setFaster]=useState(0),[effortActivity,setEffortActivity]=useState(activities[0]||''),[effortMinutes,setEffortMinutes]=useState(15);async function calc(){if(!sim)return;setImpact(await businessImpact(sim,{cases_per_month:cases,labor_cost_per_hour:labor,processing_effort_by_activity_minutes:effortActivity?{[effortActivity]:effortMinutes}:{},sla_breach_cost:breach,rework_cost:rework,automation_cost_monthly:automationCost,implementation_cost_monthly:implementationCost,value_of_faster_completion_per_hour:faster,illustrative:true}));}return <div className="stack">{!sim&&<Notice kind="warn">Run a transformation scenario first.</Notice>}<Notice>ILLUSTRATIVE USER INPUTS — these assumptions are not client actuals. OBSERVED process data, SIMULATED scenario outcomes and ESTIMATED financial effects remain separate.</Notice><div className="form-grid"><label>Cases/month<input type="number" value={cases} onChange={event=>setCases(+event.target.value)}/></label><label>Labor cost/hour<input type="number" value={labor} onChange={event=>setLabor(+event.target.value)}/></label><label>Activity for processing effort<select value={effortActivity} onChange={event=>setEffortActivity(event.target.value)}>{activities.map(item=><option key={item}>{item}</option>)}</select></label><label>Processing effort (min/case)<input type="number" min="0" value={effortMinutes} onChange={event=>setEffortMinutes(+event.target.value)}/></label><label>SLA breach cost<input type="number" value={breach} onChange={event=>setBreach(+event.target.value)}/></label><label>Rework cost<input type="number" value={rework} onChange={event=>setRework(+event.target.value)}/></label><label>Automation cost/month<input type="number" value={automationCost} onChange={event=>setAutomationCost(+event.target.value)}/></label><label>Implementation cost/month<input type="number" value={implementationCost} onChange={event=>setImplementationCost(+event.target.value)}/></label><label>Value of faster completion/hour<input type="number" value={faster} onChange={event=>setFaster(+event.target.value)}/></label></div><button className="primary" disabled={!sim} onClick={()=>void calc()}>Calculate ESTIMATED value</button>{impact&&<><Kpis><Kpi label="ESTIMATED monthly value" value={impact.estimated_monthly_value}/><Kpi label="SIMULATED lead-time saved/case" value={`${impact.lead_time_hours_saved_per_case}h`}/><Kpi label="ESTIMATED labor effort savings" value={impact.categories.labor_effort_savings}/><Kpi label="ESTIMATED SLA cost avoidance" value={impact.categories.sla_cost_avoidance}/><Kpi label="ESTIMATED rework savings" value={impact.categories.rework_savings}/><Kpi label="ESTIMATED recurring costs" value={impact.categories.recurring_costs}/></Kpis><Notice>{impact.disclaimer}</Notice></>}</div>}
function ModelEval({data,train}:{data:ModelMetrics|null;train:()=>Promise<void>}){return <div className="stack"><button className="primary" onClick={()=>void train()}>Train, evaluate & persist model</button>{data?.metrics&&<><Kpis><Kpi label="Precision" value={fmt(data.metrics.precision)}/><Kpi label="Recall" value={fmt(data.metrics.recall)}/><Kpi label="F1" value={fmt(data.metrics.f1)}/><Kpi label="ROC-AUC" value={fmt(data.metrics.roc_auc)}/><Kpi label="PR-AUC" value={fmt(data.metrics.pr_auc)}/><Kpi label="MAE" value={`${fmt(data.remaining_metrics.mae_hours)}h`}/><Kpi label="Median AE" value={`${fmt(data.remaining_metrics.median_absolute_error_hours)}h`}/><Kpi label="RMSE" value={`${fmt(data.remaining_metrics.rmse_hours)}h`}/></Kpis><ObjectGrid data={{version:data.version,training_timestamp:data.training_timestamp,...data.split}}/></>}</div>}
function asRecord(data:unknown):Record<string,unknown>|null{return data!=null&&typeof data==='object'&&!Array.isArray(data)?data as Record<string,unknown>:null;}
function ObjectGrid({data}:{data:Record<string,unknown>|null}){if(!data)return null;return <div className="object-grid">{Object.entries(data).filter(([,value])=>typeof value!=='object'||value===null).map(([key,value])=><div key={key}><span>{key.replaceAll('_',' ')}</span><b>{fmt(value)}</b></div>)}</div>}
function JsonPanel({data}:{data:unknown}){return <details className="json"><summary>Inspect structured result</summary><pre>{JSON.stringify(data,null,2)}</pre></details>}
function Assumptions(){return <div className="stack"><h2>Assumptions & limitations</h2><Notice>Observed completion timestamps provide inter-event elapsed time. Without lifecycle start/complete data, FlowLens does not call that pure waiting or processing time.</Notice><ul><li>Counterfactuals use paired common-random-number trajectory bootstrap.</li><li>SIMULATED 30-day completion volume is counted over a fixed 720h horizon under calibrated historical arrivals; it is not maximum system capacity and is independent of analysis cohort size.</li><li>Resource scenarios use explicit capacity/queue mechanics with a documented service-time proxy when lifecycle data is absent.</li><li>Parallelization is API-validated for observed adjacent activities; domain independence remains an explicit assumption.</li><li>Conditional routing uses structured predicates only and is limited to existing observed activities.</li><li>Conformance is heuristic sequence comparison, not formal token replay.</li><li>Financial outputs are ESTIMATED from explicit assumptions and never guaranteed savings.</li><li>Active-case risk uses historical snapshot cutoffs and persisted models; future events are excluded from features.</li></ul></div>}
