import {describe,it,expect} from 'vitest';
import {buildAction} from './components/ScenarioBuilder';
import {layoutActivities} from './components/ProcessMap';
import type {GraphEdge,ProcessGraph} from './types';

function graphFor(edges:Array<[string,string]>):ProcessGraph{
  const names=[...new Set(edges.flat())];
  const graphEdges:GraphEdge[]=edges.map(([source,target])=>({
    source,target,frequency:1,case_percentage:100,median_inter_event_delay_hours:1,p95_inter_event_delay_hours:1,
  }));
  return {
    activities:names.map(activity=>({activity,frequency:1,case_percentage:100,resource_count:1})),
    edges:graphEdges,case_count:1,event_count:names.length,start_activities:{},end_activities:{},terminology_note:'',
  };
}

describe('transformation builder',()=>{
  it('builds typed speedup',()=>expect(buildAction('activity_speedup','Finance','30')).toEqual({type:'activity_speedup',activity:'Finance',reduction_fraction:.3}));
  it('builds conditional automation',()=>{
    const action=buildAction('automate_eligible_cases','Finance','80');
    expect(action.type).toBe('automate_eligible_cases');
    if(action.type==='automate_eligible_cases') expect(action.conditions).toEqual([{field:'priority',op:'eq',value:'LOW'}]);
  });
  it('builds parallelization with two activities',()=>expect(buildAction('parallelize_activities','Finance','0',{secondaryActivity:'Compliance'})).toEqual({type:'parallelize_activities',first_activity:'Finance',second_activity:'Compliance'}));
  it('builds structured routing without expressions',()=>{
    const action=buildAction('route_cases','Approval','0',{secondaryActivity:'Fast Track',condition:{field:'priority',op:'eq',value:'HIGH'}});
    expect(action).toEqual({type:'route_cases',from_activity:'Approval',to_activity:'Fast Track',conditions:[{field:'priority',op:'eq',value:'HIGH'}]});
  });
});

describe('process map layout',()=>{
  it('keeps a normal DAG ordered left to right',()=>{
    const positions=layoutActivities(graphFor([['A','B'],['B','C']]));
    expect(positions.A.x).toBeLessThan(positions.B.x);
    expect(positions.B.x).toBeLessThan(positions.C.x);
  });

  it('keeps a rework cycle bounded using one SCC level',()=>{
    const positions=layoutActivities(graphFor([['A','B'],['B','C'],['C','A']]));
    const points=Object.values(positions);
    expect(points).toHaveLength(3);
    expect(new Set(points.map(point=>point.x)).size).toBe(1);
    expect(Math.max(...points.map(point=>point.x))).toBeLessThanOrEqual(900);
    expect(Math.max(...points.map(point=>point.y))).toBeLessThanOrEqual(520);
    expect(points.every(point=>Number.isFinite(point.x)&&Number.isFinite(point.y))).toBe(true);
  });
});
