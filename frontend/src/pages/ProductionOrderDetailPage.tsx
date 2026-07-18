import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Ban, CheckCircle2, Pause, Play, ScrollText } from 'lucide-react';
import { productionApi } from '../api/production';
import type { PlateJobPreviewItem } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';

const statusText:Record<string,string>={draft:'草稿',planned:'进行中',paused:'已暂停',completed:'已完成',cancelled:'已取消',pending:'等待安排',in_progress:'生产中'};
const operationText:Record<string,string>={production_order_created:'创建生产订单',production_order_paused:'暂停订单',production_order_resumed:'恢复订单',production_order_cancelled:'取消订单',plate_jobs_confirmed:'确认打印任务草稿'};

export function ProductionOrderDetailPage(){
 const id=Number(useParams().id); const qc=useQueryClient(); const refresh=()=>qc.invalidateQueries({queryKey:['production-order',id]});
 const {data:order,isLoading}=useQuery({queryKey:['production-order',id],queryFn:()=>productionApi.getOrder(id)});
 const [preview,setPreview]=useState<PlateJobPreviewItem[]|null>(null);
 const state=useMutation({mutationFn:(action:'pause'|'resume')=>productionApi.changeStatus(id,action),onSuccess:()=>{refresh();qc.invalidateQueries({queryKey:['production-orders']});}});
 const cancelOrder=useMutation({mutationFn:()=>productionApi.cancelOrder(id),onSuccess:()=>{refresh();qc.invalidateQueries({queryKey:['production-orders']});}});
 const previewJobs=useMutation({mutationFn:()=>productionApi.previewJobs(id),onSuccess:r=>setPreview(r.items)});
 const confirmJobsMutation=useMutation({mutationFn:(items:PlateJobPreviewItem[])=>productionApi.confirmJobs(id,items),onSuccess:()=>{setPreview(null);refresh();}});
 if(isLoading||!order)return <div className="p-8 text-white">加载中…</div>;
 return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
  <Link to="/production-orders" className="text-bambu-gray hover:text-white flex gap-2"><ArrowLeft size={18}/>返回生产订单</Link>
  <div className="flex flex-wrap justify-between gap-4"><div><div className="font-mono text-bambu-green">{order.order_number}</div><h1 className="text-3xl text-white font-bold">{String(order.product_snapshot?.name||'生产订单')}</h1><p className="text-bambu-gray">生产 {order.quantity} 套 · 优先级 {order.priority} · {statusText[order.status]||order.status}</p></div><div className="flex gap-2">{order.status==='planned'&&<Button variant="secondary" onClick={()=>state.mutate('pause')}><Pause size={16}/>暂停</Button>}{order.status==='paused'&&<Button onClick={()=>state.mutate('resume')}><Play size={16}/>恢复</Button>}{!['cancelled','completed'].includes(order.status)&&<Button variant="danger" onClick={()=>window.confirm('确认取消这个订单？')&&cancelOrder.mutate()}><Ban size={16}/>取消</Button>}</div></div>
  <Card><CardHeader><div className="flex flex-wrap justify-between gap-3"><div><h2 className="text-xl text-white font-semibold">需要数量与完成进度</h2><p className="text-sm text-bambu-gray">数量由后端统一计算，废品不会错误地抵扣剩余需要数量。</p></div>{order.status==='planned'&&<Button onClick={()=>previewJobs.mutate()}>预览打印任务草稿</Button>}</div></CardHeader><CardContent className="space-y-4">{order.requirements.map(r=>{const component=String(r.component_snapshot?.name||`零件 ${r.component_id}`);return <div key={r.id} className="p-4 rounded-lg bg-bambu-dark space-y-3"><div className="flex justify-between"><div><h3 className="text-white font-semibold">{component}</h3><p className="text-sm text-bambu-gray">{String(r.recipe_snapshot?.name||'打印方案')} · 每套需要 {r.unit_quantity}</p></div><span className="text-bambu-gray">{statusText[r.status]||r.status}</span></div><div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-center">{[['计划数量',r.ledger.planned],['已安排',r.ledger.reserved],['合格',r.ledger.good],['报废',r.ledger.scrap],['剩余',r.ledger.remaining]].map(([label,value])=><div key={String(label)} className="rounded bg-bambu-dark-secondary p-3"><div className="text-xs text-bambu-gray">{label}</div><div className="text-xl text-white">{value}</div></div>)}</div>{r.plate_jobs.length>0&&<p className="text-sm text-amber-300">已有 {r.plate_jobs.length} 个打印任务草稿，尚未选择打印机。</p>}</div>})}</CardContent></Card>
  {preview&&<Card><CardHeader><h2 className="text-xl text-white font-semibold">确认打印任务草稿</h2></CardHeader><CardContent className="space-y-4"><p className="text-bambu-gray">确认只会保存草稿，不会选择打印机，也不会发送打印。</p>{preview.length===0?<p className="text-white">当前没有剩余数量需要安排。</p>:preview.map(item=><div key={item.requirement_id} className="flex justify-between bg-bambu-dark rounded p-3 text-white"><span>{item.component_name} · {item.print_plan_name}</span><span>安排 {item.planned_quantity} 个</span></div>)}<div className="flex gap-2"><Button variant="secondary" onClick={()=>setPreview(null)}>返回修改</Button><Button disabled={!preview.length||confirmJobsMutation.isPending} onClick={()=>confirmJobsMutation.mutate(preview)}><CheckCircle2 size={16}/>确认保存草稿</Button></div>{confirmJobsMutation.error&&<p className="text-red-400">{String(confirmJobsMutation.error)}</p>}</CardContent></Card>}
  <Card><CardHeader><h2 className="text-xl text-white font-semibold flex gap-2"><ScrollText/>操作记录</h2></CardHeader><CardContent><div className="space-y-3">{order.operations.map(op=><div key={op.id} className="border-l-2 border-bambu-green pl-4"><div className="text-white">{operationText[op.operation_type]||op.operation_type}</div><div className="text-xs text-bambu-gray">{new Date(op.created_at).toLocaleString()}</div></div>)}</div></CardContent></Card>
 </div>;
}
