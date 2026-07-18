import { useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { ClipboardList, Plus } from 'lucide-react';
import { productionApi } from '../api/production';
import { productsApi } from '../api/products';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';

const statusText:Record<string,string>={draft:'草稿',planned:'进行中',paused:'已暂停',completed:'已完成',cancelled:'已取消'};

export function ProductionOrdersPage(){
 const navigate=useNavigate();
 const qc=useQueryClient();
 const {data:orders=[]}=useQuery({queryKey:['production-orders'],queryFn:productionApi.listOrders});
 const {data:products=[]}=useQuery({queryKey:['products'],queryFn:productsApi.list});
 const [show,setShow]=useState(false);
 const [form,setForm]=useState({order_number:'',product_id:0,quantity:1,priority:0,due_at:'',notes:''});
 const create=useMutation({mutationFn:productionApi.createOrder,onSuccess:(order)=>{qc.invalidateQueries({queryKey:['production-orders']});setShow(false);navigate(`/production-orders/${order.id}`);}});
 const submit=(e:FormEvent)=>{e.preventDefault();create.mutate({...form,due_at:form.due_at?new Date(form.due_at).toISOString():null});};
 return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
  <div className="flex flex-wrap justify-between gap-4"><div><h1 className="text-3xl font-bold text-white">生产订单</h1><p className="text-bambu-gray mt-1">按产品零件清单计算需要数量；这里只生成打印任务草稿，不选择打印机、不发送打印。</p></div><Button onClick={()=>setShow(!show)}><Plus size={18}/>新建生产订单</Button></div>
  {show&&<Card><CardContent><form onSubmit={submit} className="grid md:grid-cols-3 gap-3">
   <input required placeholder="订单编号（不能重复）" value={form.order_number} onChange={e=>setForm({...form,order_number:e.target.value})} className="stage8-input"/>
   <select required value={form.product_id} onChange={e=>setForm({...form,product_id:Number(e.target.value)})} className="stage8-input"><option value={0}>选择产品</option>{products.map(p=><option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}</select>
   <input aria-label="生产套数" required type="number" min="1" value={form.quantity} onChange={e=>setForm({...form,quantity:Number(e.target.value)})} className="stage8-input" placeholder="生产套数"/>
   <input aria-label="优先级" type="number" min="0" value={form.priority} onChange={e=>setForm({...form,priority:Number(e.target.value)})} className="stage8-input" placeholder="优先级"/>
   <input aria-label="要求完成时间" type="datetime-local" value={form.due_at} onChange={e=>setForm({...form,due_at:e.target.value})} className="stage8-input"/>
   <input placeholder="订单备注（可不填）" value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})} className="stage8-input"/>
   <Button type="submit" disabled={!form.product_id||create.isPending}>创建并计算需要数量</Button>
   {create.error&&<p className="text-red-400 md:col-span-2">{String(create.error)}</p>}
  </form></CardContent></Card>}
  {orders.length===0?<Card><CardContent className="text-center py-16 text-bambu-gray"><ClipboardList className="mx-auto mb-3"/>还没有生产订单。</CardContent></Card>:<div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{orders.map(o=><Link key={o.id} to={`/production-orders/${o.id}`}><Card className="h-full hover:border-bambu-green"><CardContent><div className="flex justify-between"><span className="font-mono text-bambu-green">{o.order_number}</span><span className="text-white">{statusText[o.status]||o.status}</span></div><h2 className="text-xl text-white font-semibold mt-4">{String(o.product_snapshot?.name||`产品 ${o.product_id}`)}</h2><p className="text-bambu-gray mt-2">生产 {o.quantity} 套 · 优先级 {o.priority}</p><p className="text-bambu-green mt-5">查看数量进度和任务草稿 →</p></CardContent></Card></Link>)}</div>}
  <style>{`.stage8-input{background:#18181b;border:1px solid #3f3f46;border-radius:.5rem;padding:.55rem .75rem;color:white;min-width:0}`}</style>
 </div>;
}
