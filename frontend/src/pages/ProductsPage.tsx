import { useState } from 'react';
import type { FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Box, Plus, Search, Upload } from 'lucide-react';
import { productsApi } from '../api/products';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';

export function ProductsPage(){
 const qc=useQueryClient(); const {data=[]}=useQuery({queryKey:['products'],queryFn:productsApi.list});
 const [show,setShow]=useState(false); const [search,setSearch]=useState(''); const [form,setForm]=useState({sku:'',name:'',description:''});
 const create=useMutation({mutationFn:productsApi.create,onSuccess:()=>{qc.invalidateQueries({queryKey:['products']});setShow(false);setForm({sku:'',name:'',description:''});}});
 const submit=(e:FormEvent)=>{e.preventDefault();create.mutate(form)};
 const rows=data.filter(p=>`${p.sku} ${p.name}`.toLowerCase().includes(search.toLowerCase()));
 return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
  <div className="flex flex-wrap gap-4 justify-between items-center"><div><h1 className="text-3xl font-bold text-white">产品资料</h1><p className="text-bambu-gray mt-1">维护产品编号、图片、每套产品需要的零件和打印方案；此页面不会发送打印。</p></div><div className="flex gap-2"><label className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-bambu-dark-tertiary text-white cursor-pointer"><Upload size={18}/>导入产品包<input className="hidden" type="file" accept=".zip" onChange={async e=>{const file=e.target.files?.[0];if(file){await productsApi.importArchive(file);qc.invalidateQueries({queryKey:['products']})}}}/></label><Button onClick={()=>setShow(!show)}><Plus size={18}/>新建产品</Button></div></div>
  {show&&<Card><CardContent><form onSubmit={submit} className="grid md:grid-cols-4 gap-3"><input required placeholder="产品编号（不能重复）" value={form.sku} onChange={e=>setForm({...form,sku:e.target.value})} className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white"/><input required placeholder="产品名称" value={form.name} onChange={e=>setForm({...form,name:e.target.value})} className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white"/><input placeholder="说明" value={form.description} onChange={e=>setForm({...form,description:e.target.value})} className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-white"/><Button type="submit" disabled={create.isPending}>保存</Button>{create.error&&<p className="text-red-400 md:col-span-4">{String(create.error)}</p>}</form></CardContent></Card>}
  <div className="relative max-w-md"><Search className="absolute left-3 top-2.5 text-bambu-gray" size={18}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索产品编号或产品名" className="w-full bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg pl-10 pr-3 py-2 text-white"/></div>
  {rows.length===0?<Card><CardContent className="text-center text-bambu-gray py-16"><Box className="mx-auto mb-3"/>还没有产品，点击“新建产品”开始。</CardContent></Card>:<div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">{rows.map(p=><Link key={p.id} to={`/products/${p.id}`}><Card className="h-full hover:border-bambu-green transition-colors"><CardContent><div className="flex justify-between"><span className="text-xs px-2 py-1 rounded bg-bambu-green/20 text-bambu-green">{p.sku}</span><span className={p.is_active?'text-green-400':'text-bambu-gray'}>{p.is_active?'启用':'停用'}</span></div><h2 className="text-xl text-white font-semibold mt-4">{p.name}</h2><p className="text-bambu-gray mt-2 line-clamp-2">{p.description||'暂无说明'}</p><p className="text-bambu-green mt-5">查看图片、产品零件清单与打印方案 →</p></CardContent></Card></Link>)}</div>}
 </div>
}
