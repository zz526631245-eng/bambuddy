import * as React from 'react';
import { QrCode } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { productionApi } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';
import { isLoopbackPage } from '../utils/mobileUrl';

const inputClass = 'bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white min-w-0';
const operationId = (prefix: string) => prefix + '-' + Date.now() + '-' + Math.random();

export function ConsumableLibraryPage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const summary = useQuery({ queryKey: ['consumable-library-summary'], queryFn: productionApi.consumableSummary });
  const [scanCode, setScanCode] = React.useState(searchParams.get('scan') || '');
  const [scanAction, setScanAction] = React.useState<'receive' | 'deplete'>('receive');
  const [message, setMessage] = React.useState('');
  const scan = useMutation({
    mutationFn: productionApi.scanConsumableUnit,
    onSuccess: result => {
      queryClient.invalidateQueries({ queryKey: ['consumable-library-summary'] });
      queryClient.invalidateQueries({ queryKey: ['consumable-library'] });
      queryClient.invalidateQueries({ queryKey: ['material-types'] });
      setMessage(result.status === 'depleted' ? '耗材已标记耗尽，并从打印机直供绑定中释放。' : '耗材已完成入库。');
      setScanCode('');
    },
  });
  const scanUnit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!scanCode.trim()) return;
    scan.mutate({ operation_id: operationId('consumable-' + scanAction), unit_code: scanCode.trim(), action: scanAction });
  };
  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    {isLoopbackPage() && <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-200">当前页面是 127.0.0.1，手机扫码链接无法访问。请使用手机可访问的 HTTPS 地址打开本页面。</div>}
    <div><h1 className="text-3xl font-bold text-white">耗材库</h1><p className="text-bambu-gray mt-1">二维码和生成数量现在归属于“材料类型”页面；本页只负责扫码入库、标记耗尽和查看总库存。</p></div>
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3">{[['总卷数', summary.data?.total], ['待入库', summary.data?.generated], ['可用库存', summary.data?.in_stock], ['使用中', summary.data?.bound], ['已耗尽', summary.data?.depleted], ['已报废', summary.data?.scrapped]].map(([label, value]) => <Card key={String(label)}><CardContent><p className="text-xs text-bambu-gray">{label}</p><p className="text-2xl text-white font-semibold mt-1">{value ?? '—'}</p></CardContent></Card>)}</div>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white flex items-center gap-2"><QrCode size={20} />扫码入库 / 标记耗尽</h2></CardHeader><CardContent><form onSubmit={scanUnit} className="grid md:grid-cols-4 gap-3 items-end">
      <label className="text-sm text-bambu-gray">耗材二维码<input aria-label="耗材二维码" required value={scanCode} onChange={event => setScanCode(event.target.value)} placeholder="扫码枪或手机二维码链接" className={'mt-1 w-full ' + inputClass} /></label>
      <label className="text-sm text-bambu-gray">动作<select aria-label="耗材动作" value={scanAction} onChange={event => setScanAction(event.target.value as 'receive' | 'deplete')} className={'mt-1 w-full ' + inputClass}><option value="receive">扫码入库</option><option value="deplete">扫码耗尽</option></select></label>
      <Button type="submit" disabled={scan.isPending}><QrCode size={16} />确认</Button><Link to="/material-types" className="text-bambu-green text-sm hover:underline">去材料类型管理二维码</Link>
    </form>{message && <p className="text-bambu-green text-sm mt-3">{message}</p>}{scan.error && <p className="text-red-400 text-sm mt-3">{String(scan.error)}</p>}</CardContent></Card>
  </div>;
}
