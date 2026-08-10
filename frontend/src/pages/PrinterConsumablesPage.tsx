import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, ScanLine } from 'lucide-react';
import { productionApi } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';

const inputClass = 'mt-1 w-full bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white';
const operationId = () => 'direct-consumable-' + Date.now() + '-' + Math.random();

export function PrinterConsumablesPage() {
  const queryClient = useQueryClient();
  const targets = useQuery({ queryKey: ['printer-consumable-targets'], queryFn: productionApi.listConsumableTargets });
  const bindings = useQuery({ queryKey: ['printer-consumables'], queryFn: productionApi.listConsumables });
  const [targetKey, setTargetKey] = React.useState('');
  const [scanCode, setScanCode] = React.useState('');
  const [material, setMaterial] = React.useState('PLA');
  const [colorHex, setColorHex] = React.useState('#FF0000');
  const [colorName, setColorName] = React.useState('');
  const [message, setMessage] = React.useState('');
  const scan = useMutation({
    mutationFn: productionApi.scanConsumable,
    onSuccess: result => {
      queryClient.invalidateQueries({ queryKey: ['printer-consumables'] });
      queryClient.invalidateQueries({ queryKey: ['printer-consumable-targets'] });
      setMessage(result.replayed ? '重复扫描已安全重放，没有产生重复记录。' : result.replaced_id ? '新耗材已登记，旧耗材已自动替换。' : '耗材已登记并绑定到打印机。');
      setScanCode('');
    },
  });
  const selected = targets.data?.find(item => item.kind + ':' + item.id === targetKey);
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected || !scanCode.trim()) return;
    scan.mutate({ operation_id: operationId(), scan_code: scanCode.trim(), material: material.trim().toUpperCase(), color_hex: colorHex, color_name: colorName.trim() || null, ...(selected.kind === 'printer' ? { printer_id: selected.id } : { virtual_printer_id: selected.id }) });
  };
  return <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-6">
    <div><h1 className="text-3xl font-bold text-white">直供耗材登记</h1><p className="text-bambu-gray mt-1">扫码新耗材后自动替换该打印机的旧直供耗材；AMS 槽位不会被修改。</p></div>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white flex items-center gap-2"><ScanLine size={20} />模拟扫码测试</h2></CardHeader><CardContent>
      <form onSubmit={submit} className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
        <label className="text-sm text-bambu-gray">打印机<select aria-label="选择打印机" required value={targetKey} onChange={event => setTargetKey(event.target.value)} className={inputClass}><option value="">选择打印机</option>{(targets.data ?? []).map(item => <option key={item.kind + ':' + item.id} value={item.kind + ':' + item.id}>{item.name} · {item.kind === 'virtual_printer' ? '软件测试' : '真实设备'}{item.model ? ' · ' + item.model : ''}</option>)}</select></label>
        <label className="text-sm text-bambu-gray">扫描码<input aria-label="扫描码" required value={scanCode} onChange={event => setScanCode(event.target.value)} placeholder="扫码枪输入后回车" className={inputClass} /></label>
        <label className="text-sm text-bambu-gray">材料<input aria-label="材料" required value={material} onChange={event => setMaterial(event.target.value)} className={inputClass} /></label>
        <label className="text-sm text-bambu-gray">颜色<span className="mt-1 flex gap-2"><input aria-label="颜色值" type="color" value={colorHex} onChange={event => setColorHex(event.target.value)} className="h-10 w-14 bg-bambu-dark" /><input aria-label="颜色名称" value={colorName} onChange={event => setColorName(event.target.value)} placeholder="例如 红色" className="flex-1 bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white" /></span></label>
        <div className="md:col-span-2 flex items-end gap-3"><Button type="submit" disabled={scan.isPending || !selected}><ScanLine size={16} />确认扫码登记</Button>{message && <span className="text-sm text-bambu-green flex items-center gap-1"><CheckCircle2 size={16} />{message}</span>}{scan.error && <span className="text-sm text-red-400">{String(scan.error)}</span>}</div>
      </form>
      <p className="text-xs text-bambu-gray mt-3">当前是软件扫码测试入口。真实扫码器后续只需调用同一个接口，不会自动连接打印机。</p>
    </CardContent></Card>
    <Card><CardHeader><h2 className="text-xl font-semibold text-white">当前直供耗材</h2></CardHeader><CardContent>{(bindings.data ?? []).length === 0 ? <p className="text-bambu-gray">还没有登记直供耗材。</p> : <div className="grid md:grid-cols-2 gap-3">{(bindings.data ?? []).map(binding => <div key={binding.id} className="rounded border border-bambu-gray-dark bg-bambu-dark p-3 flex gap-3 items-center"><span className="w-10 h-10 rounded-full border border-white/20" style={{ background: '#' + binding.color_hex.slice(0, 6) }} /><div><p className="text-white font-semibold">{binding.virtual_printer_name || binding.printer_name || '未命名打印机'}</p><p className="text-bambu-gray">{binding.material} · {binding.color_name || binding.color_hex} · 扫描码 {binding.scan_code}</p><p className="text-xs text-bambu-gray">直供耗材 · {new Date(binding.scanned_at).toLocaleString()}</p></div></div>)}</div>}</CardContent></Card>
  </div>;
}
