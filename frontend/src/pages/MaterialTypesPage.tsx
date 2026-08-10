import { useState, type FormEvent } from 'react';
import { Download, Plus, QrCode, Trash2 } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { materialsApi, type MaterialInput, type MaterialType } from '../api/materials';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';
import { Link } from 'react-router-dom';

const inputClass = 'bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white min-w-0';
const empty: MaterialInput = { code: '', material: 'PLA', subtype: '', brand: '', color_name: '', color_hex: '#FFFFFF', is_active: true };

function qrPayload(material: MaterialType): string {
  const params = new URLSearchParams({ v: '1', code: material.code, material: material.material, color: (material.color_hex || '').replace(/^#/, ''), name: material.color_name || '' });
  const payload = 'bambuddy://material?' + params.toString();
  return window.location.origin + '/printer-consumables?scan=' + encodeURIComponent(payload);
}

function downloadQr(material: MaterialType) {
  const svg = document.getElementById('material-qr-' + material.id);
  if (!svg) return;
  const blob = new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = material.code + '-二维码.svg';
  anchor.click();
  URL.revokeObjectURL(url);
}

export function MaterialTypesPage() {
  const queryClient = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ['material-types'], queryFn: materialsApi.list });
  const [form, setForm] = useState(empty);
  const create = useMutation({ mutationFn: materialsApi.create, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['material-types'] }); setForm(empty); } });
  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate(form); };
  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    <div><h1 className="text-3xl font-bold text-white">材料类型</h1><p className="text-bambu-gray mt-1">创建材料后自动生成专属二维码，手机摄像头或扫码枪都可以读取。</p></div>
    <Card><CardContent><form onSubmit={submit} className="grid sm:grid-cols-2 lg:grid-cols-7 gap-3">
      <input required placeholder="编码" value={form.code} onChange={event => setForm({ ...form, code: event.target.value })} className={inputClass} />
      <input required placeholder="材料 PLA" value={form.material} onChange={event => setForm({ ...form, material: event.target.value })} className={inputClass} />
      <input placeholder="子类型" value={form.subtype || ''} onChange={event => setForm({ ...form, subtype: event.target.value })} className={inputClass} />
      <input placeholder="品牌" value={form.brand || ''} onChange={event => setForm({ ...form, brand: event.target.value })} className={inputClass} />
      <input placeholder="颜色名" value={form.color_name || ''} onChange={event => setForm({ ...form, color_name: event.target.value })} className={inputClass} />
      <input aria-label="颜色值" type="color" value={form.color_hex || '#FFFFFF'} onChange={event => setForm({ ...form, color_hex: event.target.value })} className="h-10 w-full bg-bambu-dark rounded" />
      <Button type="submit" disabled={create.isPending}><Plus size={16} />新增</Button>
    </form>{create.error && <p className="text-red-400 text-sm mt-3">{String(create.error)}</p>}</CardContent></Card>
    <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{data.map(material => <Card key={material.id}><CardContent>
      <div className="flex justify-between"><span className="font-mono text-bambu-green">{material.code}</span><button aria-label={'删除 ' + material.code} className="text-red-400" onClick={async () => { if (confirm('确认删除？被配方或耗材引用时系统会阻止删除。')) { await materialsApi.remove(material.id); queryClient.invalidateQueries({ queryKey: ['material-types'] }); } }}><Trash2 size={17} /></button></div>
      <div className="flex gap-4 mt-4 items-center"><span className="w-10 h-10 rounded-full border border-white/20" style={{ background: material.color_hex || '#777' }} /><div><h2 className="text-white font-semibold">{material.brand || '未指定品牌'} · {material.material}{material.subtype ? ' ' + material.subtype : ''}</h2><p className="text-bambu-gray">{material.color_name || '未命名颜色'} · {material.color_hex || '无色值'}</p></div></div>
      <div className="mt-4 rounded-lg bg-white p-3 inline-flex"><QRCodeSVG id={'material-qr-' + material.id} value={qrPayload(material)} size={128} includeMargin /></div>
      <p className="text-xs text-bambu-gray mt-2 flex items-center gap-1"><QrCode size={14} />二维码内容：{material.code}</p>
      <Button type="button" variant="secondary" className="mt-3" onClick={() => downloadQr(material)}><Download size={16} />下载二维码</Button>
      <Link to={'/consumable-library?material_type_id=' + material.id} className="ml-2 inline-flex items-center justify-center font-medium rounded-lg bg-bambu-green hover:bg-bambu-green-light text-white px-3 py-2 text-sm"><QrCode size={16} />生成耗材卷</Link>
    </CardContent></Card>)}</div>
  </div>;
}
