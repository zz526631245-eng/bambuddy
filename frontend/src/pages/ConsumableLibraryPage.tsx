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
const periods = [
  ['1y', '近1年'], ['6m', '近半年'], ['3m', '近3个月'], ['30d', '近30天'],
  ['7d', '近7天'], ['3d', '近3天'], ['1d', '近1天'],
] as const;

const grams = (value: number) => `${Number(value || 0).toFixed(1)} g`;
const money = (value: number) => `¥${Number(value || 0).toFixed(2)}`;

export function ConsumableLibraryPage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const summary = useQuery({ queryKey: ['consumable-library-summary'], queryFn: productionApi.consumableSummary });
  const inventory = useQuery({ queryKey: ['consumable-inventory-summary'], queryFn: productionApi.consumableInventorySummary });
  const [period, setPeriod] = React.useState('30d');
  const [startDate, setStartDate] = React.useState('');
  const [endDate, setEndDate] = React.useState('');
  const consumption = useQuery({
    queryKey: ['consumable-consumption-summary', period, startDate, endDate],
    queryFn: () => productionApi.consumableConsumptionSummary({
      period,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    }),
    enabled: !(startDate && !endDate) && !(!startDate && endDate),
  });
  const [scanCode, setScanCode] = React.useState(searchParams.get('scan') || '');
  const [scanAction, setScanAction] = React.useState<'receive' | 'deplete'>('receive');
  const [message, setMessage] = React.useState('');
  const scan = useMutation({
    mutationFn: productionApi.scanConsumableUnit,
    onSuccess: result => {
      queryClient.invalidateQueries({ queryKey: ['consumable-library-summary'] });
      queryClient.invalidateQueries({ queryKey: ['consumable-inventory-summary'] });
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
  const filteredEvents = consumption.data?.events ?? [];
  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    {isLoopbackPage() && <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-200">当前页面是 127.0.0.1，手机扫码链接无法访问。请使用手机可访问的 HTTPS 地址打开本页面。</div>}
    <div><h1 className="text-3xl font-bold text-white">耗材库</h1><p className="text-bambu-gray mt-1">二维码入库、标记耗尽、库存数量和打印消耗成本统一在这里查看。</p></div>
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3">{[
      ['总卷数', summary.data?.total], ['待入库', summary.data?.generated], ['可用库存', summary.data?.in_stock],
      ['使用中', summary.data?.bound], ['已耗尽', summary.data?.depleted], ['已报废', summary.data?.scrapped],
    ].map(([label, value]) => <Card key={String(label)}><CardContent><p className="text-xs text-bambu-gray">{label}</p><p className="text-2xl text-white font-semibold mt-1">{value ?? '—'}</p></CardContent></Card>)}</div>

    <Card><CardHeader><h2 className="text-xl font-semibold text-white">按品牌、材料和颜色汇总库存</h2><p className="text-sm text-bambu-gray mt-1">数量由服务器统计，避免在浏览器重复计算。</p></CardHeader><CardContent>
      {(inventory.data ?? []).length === 0 ? <p className="text-sm text-bambu-gray">暂时没有生成耗材卷。</p> : <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">{(inventory.data ?? []).map((group, index) => <div key={`${group.brand ?? 'unknown'}-${group.material}-${group.subtype ?? ''}-${group.color_hex ?? group.color_name ?? ''}-${index}`} className="rounded-lg border border-bambu-gray-dark bg-bambu-dark p-4">
        <div className="flex items-start gap-3"><span className="mt-1 h-8 w-8 shrink-0 rounded-full border border-white/20" style={{ background: group.color_hex ? (group.color_hex.startsWith('#') ? group.color_hex : '#' + group.color_hex) : '#777' }} /><div className="min-w-0"><p className="text-base font-semibold text-white">{group.brand || '未指定品牌'} · {group.material}{group.subtype ? ` ${group.subtype}` : ''}</p><p className="text-sm text-bambu-gray">{group.color_name || '未命名颜色'}{group.color_hex ? ` · ${group.color_hex}` : ''}</p></div></div>
        <div className="mt-4 grid grid-cols-2 gap-2 text-center text-xs"><div className="rounded bg-bambu-dark-secondary p-2"><p className="text-bambu-gray">库存中</p><p className="mt-1 text-xl font-semibold text-bambu-green">{group.in_stock}</p></div><div className="rounded bg-bambu-dark-secondary p-2"><p className="text-bambu-gray">使用中</p><p className="mt-1 text-xl font-semibold text-blue-300">{group.bound}</p></div><div className="rounded bg-bambu-dark-secondary p-2"><p className="text-bambu-gray">待入库</p><p className="mt-1 text-lg font-semibold text-amber-300">{group.generated}</p></div><div className="rounded bg-bambu-dark-secondary p-2"><p className="text-bambu-gray">总卷数</p><p className="mt-1 text-lg font-semibold text-white">{group.total}</p></div></div>
        {(group.depleted > 0 || group.scrapped > 0) && <p className="mt-3 text-xs text-bambu-gray">已耗尽 {group.depleted} 卷 · 已报废 {group.scrapped} 卷</p>}
      </div>)}</div>}
    </CardContent></Card>

    <Card><CardHeader><h2 className="text-xl font-semibold text-white">耗材消耗与成本</h2><p className="text-sm text-bambu-gray mt-1">真实打印完成后，按切片记录的耗材克数自动扣减；价格按每卷净重比例折算。</p></CardHeader><CardContent>
      <div className="flex flex-wrap items-end gap-3"><label className="text-sm text-bambu-gray">快捷周期<select aria-label="消耗统计周期" value={period} onChange={event => { setPeriod(event.target.value); setStartDate(''); setEndDate(''); }} className={'mt-1 ' + inputClass}>{periods.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="text-sm text-bambu-gray">开始日期<input aria-label="消耗开始日期" type="date" value={startDate} onChange={event => setStartDate(event.target.value)} className={'mt-1 ' + inputClass} /></label><label className="text-sm text-bambu-gray">结束日期<input aria-label="消耗结束日期" type="date" value={endDate} onChange={event => setEndDate(event.target.value)} className={'mt-1 ' + inputClass} /></label>{(startDate || endDate) && <Button type="button" variant="secondary" onClick={() => { setStartDate(''); setEndDate(''); }}>恢复快捷周期</Button>}</div>
      {(startDate && !endDate || !startDate && endDate) && <p className="text-amber-300 text-sm mt-3">自定义日期需要同时填写开始和结束日期。</p>}
      <div className="grid sm:grid-cols-3 gap-3 mt-5"><div className="rounded-lg bg-bambu-dark p-4"><p className="text-xs text-bambu-gray">统计区间用量</p><p className="text-2xl text-white font-semibold mt-1">{grams(consumption.data?.consumed_g ?? 0)}</p></div><div className="rounded-lg bg-bambu-dark p-4"><p className="text-xs text-bambu-gray">估算材料成本</p><p className="text-2xl text-bambu-green font-semibold mt-1">{money(consumption.data?.cost ?? 0)}</p></div><div className="rounded-lg bg-bambu-dark p-4"><p className="text-xs text-bambu-gray">打印消耗记录</p><p className="text-2xl text-white font-semibold mt-1">{consumption.data?.event_count ?? 0}</p></div></div>
      {(consumption.data?.groups ?? []).length > 0 && <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3 mt-5">{consumption.data?.groups.map((group, index) => <div key={`${group.brand}-${group.material}-${group.color_hex}-${index}`} className="rounded-lg border border-bambu-gray-dark bg-bambu-dark p-4"><p className="font-semibold text-white">{group.brand || '未指定品牌'} · {group.material}{group.subtype ? ` ${group.subtype}` : ''}</p><p className="text-sm text-bambu-gray mt-1">{group.color_name || '未命名颜色'}</p><div className="mt-3 flex justify-between text-sm"><span className="text-bambu-gray">消耗</span><span className="text-white">{grams(group.consumed_g)}</span></div><div className="flex justify-between text-sm"><span className="text-bambu-gray">成本</span><span className="text-bambu-green">{money(group.cost)}</span></div></div>)}</div>}
      {filteredEvents.length > 0 && <div className="mt-5 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-bambu-gray border-b border-bambu-gray-dark"><th className="p-2">时间</th><th className="p-2">耗材卷</th><th className="p-2">材料/颜色</th><th className="p-2">消耗</th><th className="p-2">成本</th></tr></thead><tbody>{filteredEvents.map(event => <tr key={event.id} className="border-b border-bambu-gray-dark/60"><td className="p-2 text-bambu-gray">{new Date(event.recorded_at).toLocaleString()}</td><td className="p-2 font-mono text-xs text-bambu-green">{event.unit_code || '—'}</td><td className="p-2 text-white">{event.material || '—'} · {event.color_name || '—'}</td><td className="p-2 text-white">{grams(event.consumed_g)}</td><td className="p-2 text-bambu-green">{money(event.cost)}</td></tr>)}</tbody></table></div>}
      {consumption.data?.event_count === 0 && <p className="text-sm text-bambu-gray mt-5">该区间还没有自动记录的打印消耗。</p>}
      {consumption.error && <p className="text-red-400 text-sm mt-3">{String(consumption.error)}</p>}
    </CardContent></Card>

    <Card><CardHeader><h2 className="text-xl font-semibold text-white flex items-center gap-2"><QrCode size={20} />扫码入库 / 标记耗尽</h2></CardHeader><CardContent><form onSubmit={scanUnit} className="grid md:grid-cols-4 gap-3 items-end"><label className="text-sm text-bambu-gray">耗材二维码<input aria-label="耗材二维码" required value={scanCode} onChange={event => setScanCode(event.target.value)} placeholder="扫码枪或手机二维码链接" className={'mt-1 w-full ' + inputClass} /></label><label className="text-sm text-bambu-gray">动作<select aria-label="耗材动作" value={scanAction} onChange={event => setScanAction(event.target.value as 'receive' | 'deplete')} className={'mt-1 w-full ' + inputClass}><option value="receive">扫码入库</option><option value="deplete">扫码耗尽</option></select></label><Button type="submit" disabled={scan.isPending}><QrCode size={16} />确认</Button><Link to="/material-types" className="text-bambu-green text-sm hover:underline">去材料类型管理二维码</Link></form>{message && <p className="text-bambu-green text-sm mt-3">{message}</p>}{scan.error && <p className="text-red-400 text-sm mt-3">{String(scan.error)}</p>}</CardContent></Card>
  </div>;
}
