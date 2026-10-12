// @vitest-environment jsdom
import React,{act} from 'react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {createRoot,type Root} from 'react-dom/client';
import {ActiveRisk,ScenarioComparison} from './App';
import ProcessMap from './components/ProcessMap';
import ScenarioBuilder from './components/ScenarioBuilder';
import type {ProcessGraph,Scenario,SimulationResult} from './types';

(globalThis as typeof globalThis & {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;

let container:HTMLDivElement;
let root:Root;

beforeEach(()=>{
  container=document.createElement('div');
  document.body.appendChild(container);
  root=createRoot(container);
});
afterEach(async()=>{
  await act(async()=>root.unmount());
  container.remove();
});

async function render(node:React.ReactNode){
  await act(async()=>{root.render(<>{node}</>);});
}
function labelControl(text:string):HTMLLabelElement{
  const label=[...container.querySelectorAll('label')].find(item=>item.textContent?.includes(text));
  if(!label)throw new Error(`Label not found: ${text}`);
  return label;
}
async function change(element:HTMLInputElement|HTMLSelectElement,value:string){
  await act(async()=>{
    const prototype=element instanceof HTMLInputElement
      ? HTMLInputElement.prototype
      : HTMLSelectElement.prototype;

    const setter=Object.getOwnPropertyDescriptor(prototype,'value')?.set;
    if(!setter)throw new Error('Native value setter not found');

    setter.call(element,value);

    element.dispatchEvent(
      new Event(element instanceof HTMLInputElement?'input':'change',{bubbles:true})
    );
  });
}
async function click(buttonText:string){
  const button=[...container.querySelectorAll('button')].find(item=>item.textContent?.includes(buttonText));
  if(!button)throw new Error(`Button not found: ${buttonText}`);
  await act(async()=>{button.dispatchEvent(new MouseEvent('click',{bubbles:true}));});
}

const graph:ProcessGraph={
  activities:[
    {activity:'A',frequency:10,case_percentage:100,resource_count:1},
    {activity:'B',frequency:8,case_percentage:80,resource_count:2},
  ],
  edges:[{source:'A',target:'B',frequency:8,case_percentage:80,median_inter_event_delay_hours:2,p95_inter_event_delay_hours:4}],
  case_count:10,event_count:18,start_activities:{A:10},end_activities:{B:8},terminology_note:'Observed inter-event delay',
};

function scenarioResult():SimulationResult{
  const scenario:Scenario={name:'Scenario A',actions:[],runs:20,sla_hours:48,seed:42,cohort_size:100};
  const metrics={mean_cycle_hours:10,median_cycle_hours:9,p90_cycle_hours:13,p95_cycle_hours:15,sla_compliance:.9,simulated_throughput_cases_per_30d:120,estimated_process_cost:0};
  return {
    scenario,baseline:{...metrics},proposed:{...metrics,median_cycle_hours:8,simulated_throughput_cases_per_30d:125},
    simulated_impact:{median_cycle_reduction_pct:11.1,p95_cycle_delta_hours:-1,sla_compliance_delta_pp:2,throughput_delta_cases_per_30d:5},
    uncertainty:{
      cycle_time_reduction_pct:{median:11.1,p10:8,p90:14},
      median_cycle_delta_hours:{median:-1,p10:-1.5,p90:-.5},
      sla_compliance_delta_pp:{median:2,p10:1,p90:3},
    },
    baseline_fidelity:{status:'HIGH',warning:null,observed:{},simulated_baseline:{}},
    throughput_methodology:{metric:'simulated 30-day completion volume under calibrated historical arrivals',arrival_model:'Poisson',historical_arrival_rate_cases_per_hour:.16,historical_arrival_rate_cases_per_30d:120,arrival_observation_span_hours:720,simulation_horizon_hours:720,warmup_hours:20,paired_baseline_proposed_arrivals:true,independent_of_analysis_cohort_size:true},
    resource_diagnostics:[],disclaimer:'SIMULATED IMPACT',
  };
}

describe('freeze-patch UI regressions',()=>{
  it('Active Case Risk rejects stale non-case page data',async()=>{
    const train=vi.fn(async()=>{});
    await render(<ActiveRisk data={{case_count:50,activity_count:6}} train={train}/>);
    expect(container.textContent).toContain('Train & persist model first');
    expect(container.querySelector('table')).toBeNull();
  });

  it('preserves bottleneck highlighting from dedicated bottleneck state',async()=>{
    await render(<ProcessMap graph={graph} bottlenecks={['B']}/>);
    const hot=container.querySelector('rect.node.hot');
    expect(hot).not.toBeNull();
    expect(hot?.getAttribute('data-activity')).toBe('B');
  });

  it('Scenario Builder uses only safe structured condition fields',async()=>{
    const onSave=vi.fn();
    await render(<ScenarioBuilder activities={['A','B']} onRun={()=>{}} onSave={onSave}/>);
    const action=labelControl('Action').querySelector('select');
    if(!action)throw new Error('Action select missing');
    await change(action,'automate_eligible_cases');
    const field=labelControl('Condition field').querySelector('select');
    if(!field)throw new Error('Condition field select missing');
    expect([...field.options].map(option=>option.value)).toEqual(['priority','value','customer_type','region','department','channel']);
    await change(field,'region');
    const conditionValue=labelControl('Condition value').querySelector('input');
    if(!conditionValue)throw new Error('Condition value input missing');
    await change(conditionValue,'South');
    await click('Add action');
    await click('Save scenario');
    expect(onSave).toHaveBeenCalledTimes(1);
    const saved=onSave.mock.calls[0][0] as Scenario;
    const first=saved.actions[0];
    expect(first.type).toBe('automate_eligible_cases');
    if(first.type==='automate_eligible_cases')expect(first.conditions).toEqual([{field:'region',op:'eq',value:'South'}]);
  });

  it('renders scenario comparison with completion-volume terminology',async()=>{
    const result=scenarioResult();
    await render(<ScenarioComparison saved={[result.scenario]} compare={async()=>{}} data={{results:[result],comparison_basis:'paired'}}/>);
    expect(container.textContent).toContain('Scenario A');
    expect(container.textContent).toContain('SIMULATED 30-day completion volume');
    expect(container.textContent).not.toContain('SIMULATED throughput');
  });
});
