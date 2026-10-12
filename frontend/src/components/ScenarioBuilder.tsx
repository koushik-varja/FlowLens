import React, {useMemo, useState} from 'react';
import type {
  Condition,
  ConditionField,
  ConditionOperator,
  Scenario,
  TransformationAction,
} from '../types';

type ActionKind = TransformationAction['type'];
interface BuildOptions {
  secondaryActivity?: string;
  condition?: Condition;
  priority?: string;
  effortMinutes?: number;
}

export function buildAction(kind:string, activity:string, value:string, options:BuildOptions = {}):TransformationAction {
  const numeric = Number(value) || 0;
  if (kind === 'activity_speedup') return {type:'activity_speedup', activity, reduction_fraction:numeric / 100};
  if (kind === 'remove_activity') return {type:'remove_activity', activity};
  if (kind === 'add_resource_capacity') return {type:'add_resource_capacity', activity, additional_capacity:Math.max(1, Math.round(numeric || 1)), service_fraction:.35};
  if (kind === 'automate_eligible_cases') return {
    type:'automate_eligible_cases', activity,
    conditions:[options.condition ?? {field:'priority', op:'eq', value:'LOW'}],
    reduction_fraction:Math.min(.95, Math.max(.05, numeric / 100 || .8)),
    processing_effort_saved_minutes:options.effortMinutes ?? 8,
  };
  if (kind === 'parallelize_activities') return {type:'parallelize_activities', first_activity:activity, second_activity:options.secondaryActivity ?? ''};
  if (kind === 'route_cases') return {
    type:'route_cases', conditions:[options.condition ?? {field:'priority', op:'eq', value:'HIGH'}],
    from_activity:activity, to_activity:options.secondaryActivity ?? '',
  };
  if (kind === 'change_priority_routing') return {
    type:'change_priority_routing', priority:options.priority || 'HIGH', activity,
    reduction_fraction:Math.min(.95, Math.max(.05, numeric / 100 || .25)),
  };
  if (kind === 'change_sla') return {type:'change_sla', hours:Math.max(0.1, numeric)};
  throw new Error(`Unsupported transformation type: ${kind}`);
}

function actionLabel(action:TransformationAction):string {
  switch (action.type) {
    case 'parallelize_activities': return `${action.first_activity} ∥ ${action.second_activity}`;
    case 'route_cases': return `${action.from_activity} → ${action.to_activity}`;
    case 'change_sla': return `${action.hours}h`;
    case 'change_priority_routing': return `${action.priority}: ${action.activity}`;
    default: return action.activity;
  }
}

export default function ScenarioBuilder({activities,onRun,onSave}:{activities:string[];onRun:(s:Scenario)=>void;onSave:(s:Scenario)=>void}) {
  const [name,setName]=useState('Scenario A');
  const [kind,setKind]=useState<ActionKind>('activity_speedup');
  const [activity,setActivity]=useState(activities[0]||'');
  const [secondary,setSecondary]=useState(activities[1]||activities[0]||'');
  const [value,setValue]=useState('25');
  const [runs,setRuns]=useState(200);
  const [sla,setSla]=useState(48);
  const [cohort,setCohort]=useState(200);
  const [actions,setActions]=useState<TransformationAction[]>([]);
  const [conditionField,setConditionField]=useState<ConditionField>('priority');
  const [conditionOp,setConditionOp]=useState<ConditionOperator>('eq');
  const [conditionValue,setConditionValue]=useState('LOW');
  const [priority,setPriority]=useState('HIGH');
  const [effortMinutes,setEffortMinutes]=useState(8);
  const [validation,setValidation]=useState('');

  const needsSecondary=kind==='parallelize_activities'||kind==='route_cases';
  const needsCondition=kind==='automate_eligible_cases'||kind==='route_cases';
  const parameterLabel=useMemo(()=>{
    if(kind==='add_resource_capacity') return 'Additional resources';
    if(kind==='remove_activity') return 'No parameter';
    if(kind==='change_sla') return 'New SLA hours';
    return 'Reduction %';
  },[kind]);

  function add(){
    setValidation('');
    if(kind!=='change_sla' && !activity){setValidation('Select a valid activity.');return;}
    if(needsSecondary && (!secondary || secondary===activity)){setValidation('Select two different activities.');return;}
    const condition:Condition={field:conditionField,op:conditionOp,value:conditionValue};
    try{
      const next=buildAction(kind,activity,value,{secondaryActivity:secondary,condition,priority,effortMinutes});
      setActions(current=>[...current,next]);
    }catch(error){setValidation(error instanceof Error?error.message:String(error));}
  }

  const scenario:Scenario={name,actions,runs,sla_hours:sla,seed:42,cohort_size:cohort};
  return <div className="builder stack">
    <div className="form-grid">
      <label>Scenario name<input value={name} onChange={e=>setName(e.target.value)}/></label>
      <label>Action<select value={kind} onChange={e=>setKind(e.target.value as ActionKind)}>
        <option value="activity_speedup">Activity speedup</option>
        <option value="remove_activity">Remove activity</option>
        <option value="add_resource_capacity">Add resource capacity</option>
        <option value="automate_eligible_cases">Selective automation</option>
        <option value="parallelize_activities">Parallelize activities</option>
        <option value="route_cases">Conditional routing</option>
        <option value="change_priority_routing">Priority routing acceleration</option>
        <option value="change_sla">Scenario SLA override</option>
      </select></label>
      {kind!=='change_sla'&&<label>Primary activity<select value={activity} onChange={e=>setActivity(e.target.value)}>{activities.map(a=><option key={a}>{a}</option>)}</select></label>}
      {needsSecondary&&<label>{kind==='parallelize_activities'?'Activity B':'Route to activity'}<select value={secondary} onChange={e=>setSecondary(e.target.value)}>{activities.map(a=><option key={a}>{a}</option>)}</select></label>}
      {kind!=='remove_activity'&&<label>{parameterLabel}<input value={value} onChange={e=>setValue(e.target.value)} aria-label="scenario parameter"/></label>}
      {needsCondition&&<>
        <label>Condition field<select value={conditionField} onChange={e=>setConditionField(e.target.value as ConditionField)}><option>priority</option><option>value</option><option>customer_type</option><option>region</option><option>department</option><option>channel</option></select></label>
        <label>Operator<select value={conditionOp} onChange={e=>setConditionOp(e.target.value as ConditionOperator)}><option value="eq">equals</option><option value="neq">not equal</option><option value="lt">less than</option><option value="lte">≤</option><option value="gt">greater than</option><option value="gte">≥</option></select></label>
        <label>Condition value<input value={conditionValue} onChange={e=>setConditionValue(e.target.value)}/></label>
      </>}
      {kind==='automate_eligible_cases'&&<label>Processing effort saved (min)<input type="number" min="0" value={effortMinutes} onChange={e=>setEffortMinutes(Number(e.target.value))}/></label>}
      {kind==='change_priority_routing'&&<label>Priority segment<input value={priority} onChange={e=>setPriority(e.target.value)}/></label>}
      <label>Paired runs<input type="number" min="20" max="2000" value={runs} onChange={e=>setRuns(Number(e.target.value))}/></label>
      <label>Analysis cohort<input type="number" min="10" max="1000" value={cohort} onChange={e=>setCohort(Number(e.target.value))}/></label>
      <label>Process SLA hours<input type="number" value={sla} onChange={e=>setSla(Number(e.target.value))}/></label>
    </div>
    {kind==='parallelize_activities'&&<div className="notice info">The API validates that Activity A → Activity B is an observed adjacent dependency before simulation.</div>}
    {kind==='route_cases'&&<div className="notice info">Routing uses safe structured conditions only. Current routing is limited to existing observed activities and preserves the empirical transition delay unless another action changes it.</div>}
    {validation&&<div className="notice warn">{validation}</div>}
    <div className="row"><button onClick={add}>Add action</button><button onClick={()=>setActions([])}>Clear</button><button className="primary" onClick={()=>onRun(scenario)}>Run paired simulation</button><button onClick={()=>onSave(scenario)}>Save scenario</button></div>
    <div className="action-list">{actions.length===0?<span className="muted">No actions = strict no-op scenario.</span>:actions.map((a,i)=><div key={`${a.type}-${i}`}><code>{a.type}</code> {actionLabel(a)}<button onClick={()=>setActions(xs=>xs.filter((_,j)=>j!==i))}>×</button></div>)}</div>
  </div>;
}
