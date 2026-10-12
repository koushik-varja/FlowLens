import type {ActiveCaseResponse,BusinessAssumptions,BusinessImpact,ModelMetrics,Scenario,ScenarioResult} from './types';

const API=(import.meta.env.VITE_API_URL as string|undefined)||'http://localhost:8000';

async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const response=await fetch(`${API}${path}`,init);
  const body=await response.json().catch(()=>({detail:`HTTP ${response.status}`})) as {detail?:string;error?:string};
  if(!response.ok) throw new Error(body.detail||body.error||`HTTP ${response.status}`);
  return body as T;
}
export async function uploadDataset(file:File){const fd=new FormData();fd.append('file',file);return request<{id:number;quality:Record<string,unknown>}>('/datasets',{method:'POST',body:fd});}
export const getProcess=<T>(id:number,path:string)=>request<T>(`/processes/${id}/${path}`);
export const postProcess=<T>(id:number,path:string,body:unknown)=>request<T>(`/processes/${id}/${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export const trainModel=(id:number)=>request<ModelMetrics>(`/models/${id}/train`,{method:'POST'});
export const activeCases=(id:number)=>request<ActiveCaseResponse>(`/models/${id}/active-cases`);
export const runScenario=(id:number,scenario:Scenario)=>postProcess<ScenarioResult>(id,'simulation',scenario);
export const compareScenarios=(id:number,scenarios:Scenario[])=>postProcess<{results:ScenarioResult[];comparison_basis:string}>(id,'simulation/compare',{scenarios});
export const businessImpact=(simulation:ScenarioResult, assumptions:BusinessAssumptions)=>request<BusinessImpact>('/impact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({simulation,assumptions})});
