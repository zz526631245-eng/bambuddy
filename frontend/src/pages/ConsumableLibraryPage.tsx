import * as React from 'react';
import { Download, PackagePlus, QrCode, Trash2 } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { QRCodeSVG } from 'qrcode.react';
import { Link, useSearchParams } from 'react-router-dom';
import { materialsApi } from '../api/materials';
import { productionApi, type ConsumableUnit } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';
import { isLoopbackPage, mobileBaseUrl } from '../utils/mobileUrl';

const inputClass = 'bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white min-w-0';
const operationId = (prefix: string) => prefix + '-' + Date.now() + '-' + Math.random();
const statusText: Record<string, string> = { generated: '已生成标签', in_stock: '已入库', bound: '使用中', depleted: '已耗尽', scrapped: '已报废' };

function qrValue(unit: ConsumableUnit): string {
  return mobileBaseUrl() + '/consumable-library?scan=' + encodeURIComponent(unit.unit_code);
}

function downloadQr(unit: ConsumableUnit) {
  const svg = document.getElementById('unit-qr-' + unit.id);
  if (!svg) return;
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = unit.unit_code + '.svg';
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ConsumableLibraryPage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const materials = useQuery({ queryKey: ['material-types'], queryFn: materialsApi.list });
  const targets = useQuery({ queryKey: ['printer-consumable-targets'], queryFn: productionApi.listConsumableTargets });
  const units = useQuery({ queryKey: ['consumable-library'], queryFn: () => productionApi.listConsumableUnits() });
  const summary = useQuery({ queryKey: ['consumable-library-summary'], queryFn: productionApi.consumableSummary });
  const initialMaterial = Number(searchParams.get('material_type_id') || 0);
  const [materialTypeId, setMaterialTypeId] = React.useState(initialMaterial);
  const [quantity, setQuantity] = React.useState(1);
  const [weight, setWeight] = React.useState('');
  const [scanCode, setScanCode] = React.useState(searchParams.get('scan') || '');
  const [scanAction, setScanAction] = React.useState<'receive' | 'deplete'>('receive');
  const [message, setMessage] = React.useState('');
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['consumable-library'] });
    queryClient.invalidateQueries({ queryKey: ['consumable-library-summary'] });
  };
  const batch = useMutation({
    mutationFn: productionApi.generateConsumableBatch,
    onSuccess: result => { refresh(); setMessage('已生成 ' + result.items.length + ' 个唯一二维码，请下载或打印标签。'); },
  });
  const scan = useMutation({
    mutationFn: productionApi.scanConsumableUnit,
    onSuccess: result => { refresh(); setMessage(result.status === 'depleted' ? '耗材已标记耗尽，并从打印机直供绑定中释放。' : '耗材已完成入库。'); setScanCode(''); },
  });
  const createBatch = (event: React.FormEvent) => {
    event.preventDefault();
    if (!materialTypeId) return;
    batch.mutate({ operation_id: operationId('consumable-batch'), material_type_id: materialTypeId, quantity, remaining_weight_g: weight ? Number(weight) : null });
  };
  const scanUnit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!scanCode.trim()) return;
    scan.mutate({ operation_id: operationId('consumable-' + scanAction), unit_code: scanCode.trim(), action: scanAction });
  };
  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    {isLoopbackPage() && !import.meta.env.VITE_PUBLIC_BASE_URL && <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-200">当前页面是 127.0.0.1，生成的二维码手机无法访问。请用手机可访问的 HTTPS 地址打开本页，或配置 VITE_PUBLIC_BASE_URL 后再生成标签。</div>}
    <div><h1 className="text-3xl font-bold text-white">耗材库</h1><p className="text-bambu-gray mt-1">先生成唯一耗材卷二维码，贴标后扫码入库；耗尽时再次扫码即可从可用库存移除。</p></div>
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3">{[['总卷数', summary.data?.total], ['待入库', summary.data?.generated], ['可用库存', summary.data?.in_stock], ['使用中', summary.data?.bound], ['已耗尽', summary.data?.depleted], ['已报废', summary.data?.scrapped]].map(([label, value]) => <Card key={String(label)}><CardContent><p className="text-xs text-bambu-gray">{label}</p><p className="text-2xl text-white font-semibold mt-1">{value ?? '—'}</p></CardContent></Card>)}</div>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white flex items-center gap-2"><PackagePlus size={20} />批量生成耗材卷二维码</h2></CardHeader><CardContent><form onSubmit={createBatch} className="grid md:grid-cols-4 gap-3 items-end">
      <label className="text-sm text-bambu-gray">耗材类型<select aria-label="选择耗材类型" required value={materialTypeId || ''} onChange={event => setMaterialTypeId(Number(event.target.value))} className={'mt-1 w-full ' + inputClass}><option value="">选择耗材类型</option>{(materials.data ?? []).filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.brand || '未指定品牌'} · {item.material} · {item.color_name || item.color_hex || '未命名颜色'}</option>)}</select></label>
      <label className="text-sm text-bambu-gray">生成数量<input aria-label="生成数量" type="number" min="1" max="1000" value={quantity} onChange={event => setQuantity(Number(event.target.value))} className={'mt-1 w-full ' + inputClass} /></label>
      <label className="text-sm text-bambu-gray">单卷标称重量（克）<input aria-label="单卷标称重量" type="number" min="1" value={weight} onChange={event => setWeight(event.target.value)} placeholder="可选" className={'mt-1 w-full ' + inputClass} /></label>
      <Button type="submit" disabled={batch.isPending || !materialTypeId}><QrCode size={16} />生成唯一二维码</Button>
    </form>{message && <p className="text-bambu-green text-sm mt-3">{message}</p>}{batch.error && <p className="text-red-400 text-sm mt-3">{String(batch.error)}</p>}</CardContent></Card>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white">扫码入库 / 标记耗尽</h2></CardHeader><CardContent><form onSubmit={scanUnit} className="grid md:grid-cols-4 gap-3 items-end">
      <label className="text-sm text-bambu-gray">耗材二维码<input aria-label="耗材二维码" required value={scanCode} onChange={event => setScanCode(event.target.value)} placeholder="扫码枪或手机二维码链接" className={'mt-1 w-full ' + inputClass} /></label>
      <label className="text-sm text-bambu-gray">动作<select aria-label="耗材动作" value={scanAction} onChange={event => setScanAction(event.target.value as 'receive' | 'deplete')} className={'mt-1 w-full ' + inputClass}><option value="receive">扫码入库</option><option value="deplete">扫码耗尽</option></select></label>
      <Button type="submit" disabled={scan.isPending}><QrCode size={16} />确认</Button><Link to="/printer-consumables" className="text-bambu-green text-sm hover:underline">去绑定打印机</Link>
    </form>{scan.error && <p className="text-red-400 text-sm mt-3">{String(scan.error)}</p>}</CardContent></Card>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white">打印机二维码</h2></CardHeader><CardContent><p className="text-sm text-bambu-gray mb-4">手机先扫描打印机二维码，登记页面会自动锁定目标打印机，不再需要手动选择。</p><div className="grid md:grid-cols-3 xl:grid-cols-5 gap-4">{(targets.data ?? []).map(target => { const value = mobileBaseUrl() + '/printer-consumables?printer=' + target.kind + ':' + target.id; return <div key={target.kind + ':' + target.id} className="rounded-lg bg-bambu-dark p-3 text-center"><p className="text-white font-semibold">{target.name}</p><p className="text-xs text-bambu-gray mb-2">{target.kind === 'virtual_printer' ? '软件测试打印机' : '真实打印机'}{target.model ? ' · ' + target.model : ''}</p><div className="inline-flex bg-white p-2 rounded"><QRCodeSVG value={value} size={120} includeMargin /></div><p className="text-xs text-bambu-gray mt-2">扫码后自动锁定</p></div>; })}</div></CardContent></Card>
    <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{(units.data ?? []).map(unit => <Card key={unit.id}><CardContent><div className="flex justify-between items-start"><div><span className="font-mono text-bambu-green text-sm">{unit.unit_code}</span><h3 className="text-white font-semibold mt-1">{unit.brand || '未指定品牌'} · {unit.material} · {unit.color_name || unit.color_hex || '未命名颜色'}</h3><p className="text-bambu-gray text-sm">{statusText[unit.status] || unit.status}{unit.storage_location ? ' · ' + unit.storage_location : ''}</p></div><span className="text-xs rounded px-2 py-1 bg-bambu-dark-tertiary text-white">{statusText[unit.status] || unit.status}</span></div><div className="mt-4 rounded-lg bg-white p-3 inline-flex"><QRCodeSVG id={'unit-qr-' + unit.id} value={qrValue(unit)} size={150} includeMargin /></div><div className="flex gap-2 mt-3"><Button type="button" size="sm" variant="secondary" onClick={() => downloadQr(unit)}><Download size={15} />下载二维码</Button>{unit.status === 'generated' && <button type="button" className="text-red-400" aria-label={'删除标签 ' + unit.unit_code} title="生成错误时删除标签" onClick={() => setMessage('已生成的二维码不可直接删除，请保留审计记录。')}><Trash2 size={15} /></button>}</div></CardContent></Card>)}</div>
  </div>;
}
