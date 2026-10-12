import React from 'react';
export function Kpi({label,value,note}:{label:string;value:React.ReactNode;note?:string}){return <div className="kpi"><span>{label}</span><strong>{value}</strong>{note&&<small>{note}</small>}</div>}
export function Kpis({children}:{children:React.ReactNode}){return <div className="kpis">{children}</div>}
export function DataTable({rows,columns}:{rows:Record<string,unknown>[];columns:string[]}){return <div className="table-wrap"><table><thead><tr>{columns.map(c=><th key={c}>{c.replaceAll('_',' ')}</th>)}</tr></thead><tbody>{rows.slice(0,80).map((r,i)=><tr key={i}>{columns.map(c=><td key={c}>{typeof r[c]==='object'?JSON.stringify(r[c]):String(r[c]??'—')}</td>)}</tr>)}</tbody></table></div>}
export function Notice({children,kind='info'}:{children:React.ReactNode;kind?:'info'|'warn'|'ok'}){return <div className={`notice ${kind}`}>{children}</div>}
