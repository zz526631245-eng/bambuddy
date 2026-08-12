import { useState, type FormEvent } from 'react';
import { Download, PackagePlus, Plus, QrCode, Trash2 } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { materialsApi, type MaterialInput, type MaterialType } from '../api/materials';
import { productionApi, type ConsumableUnit } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';
import { HubNav } from '../components/HubNav';
import { isLoopbackPage, mobileBaseUrl } from '../utils/mobileUrl';

const inputClass = 'bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white min-w-0';
const empty: MaterialInput = { code: '', material: 'PLA', subtype: '', brand: '', color_name: '', color_hex: '#FFFFFF', is_active: true };
const statusText: Record<string, string> = { generated: '待入库', in_stock: '已入库', bound: '使用中', depleted: '已耗尽', scrapped: '已报废' };

function operationId(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
}

function materialQrPayload(material: MaterialType): string {
  const params = new URLSearchParams({ v: '1', code: material.code, material: material.material, color: (material.color_hex || '').replace(/^#/, ''), name: material.color_name || '' });
  return mobileBaseUrl() + '/printer-consumables?scan=' + encodeURIComponent('bambuddy://material?' + params.toString());
}

function consumableQrPayload(unit: ConsumableUnit): string {
  return mobileBaseUrl() + '/consumable-library?scan=' + encodeURIComponent(unit.unit_code);
}

function downloadQr(id: string, filename: string) {
  const svg = document.getElementById(id);
  if (!svg) return;
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function MaterialTypesPage() {
  const queryClient = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ['material-types'], queryFn: materialsApi.list });
  const [form, setForm] = useState(empty);
  const [generateMaterial, setGenerateMaterial] = useState<MaterialType | null>(null);
  const [quantity, setQuantity] = useState(1);
  const create = useMutation({
    mutationFn: materialsApi.create,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['material-types'] }); setForm(empty); },
  });
  const batch = useMutation({
    mutationFn: productionApi.generateConsumableBatch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['material-types'] });
      queryClient.invalidateQueries({ queryKey: ['consumable-library'] });
      setGenerateMaterial(null);
      setQuantity(1);
    },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate(form); };
  const generate = (event: FormEvent) => {
    event.preventDefault();
    if (!generateMaterial || quantity < 1) return;
    batch.mutate({ operation_id: operationId('consumable-batch'), material_type_id: generateMaterial.id, quantity });
  };

  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    {isLoopbackPage() && !import.meta.env.VITE_PUBLIC_BASE_URL && <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-200">当前页面是 127.0.0.1，生成的二维码手机无法访问。请使用手机可访问的 HTTPS 地址打开本页面，或配置 VITE_PUBLIC_BASE_URL。</div>}
    <div><h1 className="text-3xl font-bold text-white">材料类型</h1><p className="text-bambu-gray mt-1">每种材料类型单独管理耗材卷数量、入库状态和唯一二维码。</p></div>
    <HubNav ariaLabel="耗材中心导航" items={[
      { to: '/material-types', label: '材料类型' },
      { to: '/consumable-library', label: '扫码入库' },
      { to: '/printer-consumables', label: '打印机绑定' },
    ]} />
    <Card><CardContent><form onSubmit={submit} className="grid sm:grid-cols-2 lg:grid-cols-7 gap-3">
      <input required placeholder="编码" value={form.code} onChange={event => setForm({ ...form, code: event.target.value })} className={inputClass} />
      <input required placeholder="材料 PLA" value={form.material} onChange={event => setForm({ ...form, material: event.target.value })} className={inputClass} />
      <input placeholder="子类型" value={form.subtype || ''} onChange={event => setForm({ ...form, subtype: event.target.value })} className={inputClass} />
      <input placeholder="品牌" value={form.brand || ''} onChange={event => setForm({ ...form, brand: event.target.value })} className={inputClass} />
      <input placeholder="颜色名" value={form.color_name || ''} onChange={event => setForm({ ...form, color_name: event.target.value })} className={inputClass} />
      <input aria-label="颜色值" type="color" value={form.color_hex || '#FFFFFF'} onChange={event => setForm({ ...form, color_hex: event.target.value })} className="h-10 w-full bg-bambu-dark rounded" />
      <Button type="submit" disabled={create.isPending}><Plus size={16} />新增</Button>
    </form>{create.error && <p className="text-red-400 text-sm mt-3">{String(create.error)}</p>}</CardContent></Card>

    <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{data.map(material => {
      const stats = material.consumable_stats;
      const materialUnits = stats?.units || [];
      return <Card key={material.id}><CardContent>
        <div className="flex justify-between"><span className="font-mono text-bambu-green">{material.code}</span><button aria-label={'删除 ' + material.code} className="text-red-400" onClick={async () => { if (confirm('确认删除？被配方或耗材引用时系统会阻止删除。')) { await materialsApi.remove(material.id); queryClient.invalidateQueries({ queryKey: ['material-types'] }); } }}><Trash2 size={17} /></button></div>
        <div className="flex gap-4 mt-4 items-center"><span className="w-10 h-10 rounded-full border border-white/20" style={{ background: material.color_hex || '#777' }} /><div><h2 className="text-white font-semibold">{material.brand || '未指定品牌'} · {material.material}{material.subtype ? ' ' + material.subtype : ''}</h2><p className="text-bambu-gray">{material.color_name || '未命名颜色'} · {material.color_hex || '无颜色值'}</p></div></div>
        <div className="grid grid-cols-3 gap-2 mt-4 text-center text-xs"><div className="rounded bg-bambu-dark p-2"><p className="text-bambu-gray">总卷数</p><p className="text-white text-lg">{stats?.total ?? 0}</p></div><div className="rounded bg-bambu-dark p-2"><p className="text-bambu-gray">已入库</p><p className="text-bambu-green text-lg">{stats?.received ?? '—'}</p></div><div className="rounded bg-bambu-dark p-2"><p className="text-bambu-gray">待入库</p><p className="text-amber-300 text-lg">{stats?.generated ?? '—'}</p></div></div>
        <div className="mt-4 rounded-lg bg-white p-3 inline-flex"><QRCodeSVG id={'material-qr-' + material.id} value={materialQrPayload(material)} size={128} includeMargin /></div>
        <p className="text-xs text-bambu-gray mt-2 flex items-center gap-1"><QrCode size={14} />材料类型二维码：{material.code}</p>
        <Button type="button" variant="secondary" className="mt-3" onClick={() => setGenerateMaterial(material)}><PackagePlus size={16} />生成耗材卷二维码</Button>
        <Button type="button" variant="secondary" className="mt-3 ml-2" onClick={() => downloadQr('material-qr-' + material.id, material.code + '-material.svg')}><Download size={16} />下载材料二维码</Button>
        <div className="mt-5 border-t border-bambu-gray-dark pt-4"><h3 className="text-white font-semibold">该材料的耗材卷二维码</h3><p className="text-xs text-bambu-gray mt-1">按生成时间从新到旧排列；扫码入库后才可绑定打印机。</p>{materialUnits.length === 0 && <p className="text-sm text-bambu-gray mt-3">暂未生成耗材卷。</p>}<div className="space-y-3 mt-3">{materialUnits.map(unit => <div key={unit.id} className="rounded-lg bg-bambu-dark p-3"><div className="flex justify-between gap-2"><span className="font-mono text-bambu-green text-xs break-all">{unit.unit_code}</span><span className="text-xs text-white">{statusText[unit.status] || unit.status}</span></div><div className="mt-2 flex items-center gap-3"><div className="inline-flex bg-white p-1 rounded"><QRCodeSVG id={'unit-qr-' + unit.id} value={consumableQrPayload(unit)} size={96} includeMargin /></div><div className="text-xs text-bambu-gray"><p>生成时间：{new Date(unit.generated_at).toLocaleString()}</p><Button type="button" size="sm" variant="secondary" className="mt-2" onClick={() => downloadQr('unit-qr-' + unit.id, unit.unit_code + '.svg')}><Download size={14} />下载此卷二维码</Button></div></div></div>)}</div></div>
      </CardContent></Card>;
    })}</div>

    {generateMaterial && <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"><Card className="w-full max-w-md"><CardContent><h2 className="text-xl font-semibold text-white">生成耗材卷二维码</h2><p className="text-bambu-gray mt-2">{generateMaterial.brand || '未指定品牌'} · {generateMaterial.material} · {generateMaterial.color_name || generateMaterial.color_hex}</p><form onSubmit={generate} className="mt-5 space-y-4"><label className="block text-sm text-bambu-gray">需要生成的卷数<input aria-label="生成数量" type="number" min="1" max="1000" value={quantity} onChange={event => setQuantity(Number(event.target.value))} className={'mt-1 w-full ' + inputClass} /></label>{batch.error && <p className="text-red-400 text-sm">{String(batch.error)}</p>}<div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setGenerateMaterial(null)}>取消</Button><Button type="submit" disabled={batch.isPending || quantity < 1}>生成二维码</Button></div></form></CardContent></Card></div>}
  </div>;
}
