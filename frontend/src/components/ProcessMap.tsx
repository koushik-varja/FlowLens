import React,{useMemo,useState} from 'react';
import type {ProcessGraph} from '../types';

type Point={x:number;y:number};

/**
 * Cycle-safe layout based on strongly connected components (Tarjan) followed by
 * longest-path levels on the SCC condensation DAG. Nodes in the same SCC share
 * a horizontal level, so rework loops cannot keep pushing each other rightward.
 */
export function layoutActivities(graph:ProcessGraph):Record<string,Point>{
  const names=graph.activities.map(activity=>activity.activity);
  const known=new Set(names);
  const adjacency=new Map<string,string[]>();
  names.forEach(name=>adjacency.set(name,[]));
  graph.edges.forEach(edge=>{
    if(known.has(edge.source)&&known.has(edge.target)) adjacency.get(edge.source)?.push(edge.target);
  });

  let index=0;
  const indices=new Map<string,number>();
  const lowLink=new Map<string,number>();
  const stack:string[]=[];
  const onStack=new Set<string>();
  const components:string[][]=[];

  function visit(node:string){
    indices.set(node,index);
    lowLink.set(node,index);
    index+=1;
    stack.push(node);
    onStack.add(node);

    for(const next of adjacency.get(node)??[]){
      if(!indices.has(next)){
        visit(next);
        lowLink.set(node,Math.min(lowLink.get(node)??0,lowLink.get(next)??0));
      }else if(onStack.has(next)){
        lowLink.set(node,Math.min(lowLink.get(node)??0,indices.get(next)??0));
      }
    }

    if(lowLink.get(node)===indices.get(node)){
      const component:string[]=[];
      while(stack.length){
        const member=stack.pop();
        if(member===undefined)break;
        onStack.delete(member);
        component.push(member);
        if(member===node)break;
      }
      components.push(component.sort((a,b)=>a.localeCompare(b)));
    }
  }
  names.forEach(name=>{if(!indices.has(name))visit(name);});

  const componentOf=new Map<string,number>();
  components.forEach((component,componentIndex)=>component.forEach(name=>componentOf.set(name,componentIndex)));
  const outgoing=components.map(()=>new Set<number>());
  const indegree=components.map(()=>0);
  graph.edges.forEach(edge=>{
    const source=componentOf.get(edge.source),target=componentOf.get(edge.target);
    if(source===undefined||target===undefined||source===target||outgoing[source].has(target))return;
    outgoing[source].add(target);
    indegree[target]+=1;
  });

  const level=components.map(()=>0);
  const queue=indegree.map((degree,i)=>degree===0?i:-1).filter(i=>i>=0);
  for(let cursor=0;cursor<queue.length;cursor+=1){
    const current=queue[cursor];
    for(const target of outgoing[current]){
      level[target]=Math.max(level[target],level[current]+1);
      indegree[target]-=1;
      if(indegree[target]===0)queue.push(target);
    }
  }

  const componentsByLevel=new Map<number,number[]>();
  components.forEach((component,componentIndex)=>{
    const currentLevel=level[componentIndex];
    const row=componentsByLevel.get(currentLevel)??[];
    row.push(componentIndex);
    componentsByLevel.set(currentLevel,row);
  });

  const out:Record<string,Point>={};
  for(const [currentLevel,componentIndexes] of [...componentsByLevel.entries()].sort((a,b)=>a[0]-b[0])){
    componentIndexes.sort((a,b)=>(components[a][0]??'').localeCompare(components[b][0]??''));
    let y=80;
    for(const componentIndex of componentIndexes){
      const members=components[componentIndex];
      members.forEach((name,memberIndex)=>{
        out[name]={x:120+currentLevel*220,y:y+memberIndex*92};
      });
      y+=Math.max(1,members.length)*92+48;
    }
  }
  return out;
}

export default function ProcessMap({graph,bottlenecks=[]}:{graph:ProcessGraph;bottlenecks?:string[]}){
  const[pos,setPos]=useState({x:0,y:0,scale:1});const[selected,setSelected]=useState<string|null>(null);const points=useMemo(()=>layoutActivities(graph),[graph]);
  const width=Math.max(900,...Object.values(points).map(point=>point.x+180));const height=Math.max(520,...Object.values(points).map(point=>point.y+80));
  const node=graph.activities.find(activity=>activity.activity===selected);
  return <div className="map-wrap"><div className="map-controls"><button onClick={()=>setPos(current=>({...current,scale:Math.min(1.8,current.scale+.15)}))}>＋</button><button onClick={()=>setPos(current=>({...current,scale:Math.max(.6,current.scale-.15)}))}>－</button><button onClick={()=>setPos({x:0,y:0,scale:1})}>Reset</button></div><div className="map-canvas"><svg width="100%" height="540" viewBox={`0 0 ${width} ${height}`}><g transform={`translate(${pos.x} ${pos.y}) scale(${pos.scale})`}>
    {graph.edges.map((edge,i)=>{const source=points[edge.source],target=points[edge.target];if(!source||!target)return null;return <g key={i}><line x1={source.x+72} y1={source.y} x2={target.x-72} y2={target.y} className="edge"/><text x={(source.x+target.x)/2} y={(source.y+target.y)/2-6} className="edge-label">{edge.frequency} · {edge.median_inter_event_delay_hours.toFixed(1)}h</text></g>})}
    {graph.activities.map(activity=>{const point=points[activity.activity];const hot=bottlenecks.includes(activity.activity);return <g key={activity.activity} onClick={()=>setSelected(activity.activity)} className="map-node"><rect x={point.x-72} y={point.y-28} width="144" height="56" rx="8" className={hot?'node hot':'node'} data-activity={activity.activity}/><text x={point.x} y={point.y-3} textAnchor="middle" className="node-title">{activity.activity}</text><text x={point.x} y={point.y+15} textAnchor="middle" className="node-meta">{activity.frequency} events · {activity.case_percentage}% cases</text></g>})}
  </g></svg></div>{node&&<aside className="drawer"><strong>{node.activity}</strong><span>Frequency {node.frequency}</span><span>Cases {node.case_percentage}%</span><span>Observed resources {node.resource_count}</span><small>Edge times are observed inter-event delay, not pure waiting/processing time.</small></aside>}</div>
}
