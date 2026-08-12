import { useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock3, Link2, Radio, RefreshCw, Wrench } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { productionApi, type ProductionPrinterState, type ProductionPrinterStatus } from '../api/production';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';

const operationId = (prefix: string) => `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
const stateLabels: Record<ProductionPrinterState, string> = {
  unknown: '未开始上报', idle: '空闲', printing: '打印中', paused: '已暂停', finished: '已完成', offline: '离线', error: '故障', maintenance: '维修中',
};
const stateClasses: Record<ProductionPrinterState, string> = {
  unknown: 'bg-gray-500/20 text-gray-300', idle: 'bg-bambu-green/20 text-bambu-green', printing: 'bg-blue-500/20 text-blue-300',
  paused: 'bg-amber-500/20 text-amber-300', finished: 'bg-cyan-500/20 text-cyan-300', offline: 'bg-gray-500/20 text-gray-300',
  error: 'bg-red-500/20 text-red-300', maintenance: 'bg-orange-500/20 text-orange-300',
};

function StatusBadge({ state }: { state: ProductionPrinterState }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs ${stateClasses[state] || stateClasses.unknown}`}>
    {state === 'error' || state === 'maintenance' ? <AlertTriangle size={13} /> : state === 'offline' ? <Radio size={13} /> : <CheckCircle2 size={13} />}
    {stateLabels[state] || state}
  </span>;
}

function PrinterStatusCard({ item }: { item: ProductionPrinterStatus }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ProductionPrinterState>(item.state === 'unknown' ? 'idle' : item.state);
  const [faultMessage, setFaultMessage] = useState(item.fault_message || '');
  const heartbeat = useMutation({
    mutationFn: () => productionApi.heartbeatPrinter({
      operation_id: operationId('stage13-heartbeat'), target_type: item.target_type, target_id: item.target_id, state,
      fault_code: state === 'error' || state === 'maintenance' ? 'STAGE13-SIMULATED' : null,
      fault_message: state === 'error' || state === 'maintenance' ? faultMessage || '阶段13模拟状态' : null,
      current_job_id: item.current_job_id, current_job_state: state === 'printing' ? 'printing' : null,
      loaded_filaments: item.loaded_filaments, telemetry: { simulator: true },
    }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['production-printer-status'] }); },
  });
  const effective = item.effective_state;
  return <Card className="h-full">
    <CardContent className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div><p className="text-xs text-bambu-gray">{item.target_type === 'virtual_printer' ? '软件测试打印机' : '实体打印机'} · {item.model || '未指定型号'}</p><h2 className="text-xl font-semibold text-white mt-1">{item.name}</h2></div>
        <StatusBadge state={effective} />
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-bambu-dark p-2"><p className="text-bambu-gray">分配资格</p><p className={item.available_for_allocation ? 'text-bambu-green mt-1' : 'text-red-300 mt-1'}>{item.available_for_allocation ? '可分配' : '暂不可分配'}</p></div>
        <div className="rounded-lg bg-bambu-dark p-2"><p className="text-bambu-gray">心跳</p><p className="text-white mt-1">{item.seconds_since_heartbeat == null ? '未上报' : `${item.seconds_since_heartbeat} 秒前`}</p></div>
      </div>
      <p className="text-xs text-bambu-gray flex items-center gap-1"><Clock3 size={13} />{item.last_heartbeat_at ? `最后心跳：${new Date(item.last_heartbeat_at).toLocaleString()}` : '尚未收到阶段13心跳'}</p>
      {(item.current_job_id || item.fault_message) && <div className="rounded-lg border border-bambu-gray-dark p-3 text-xs text-bambu-gray">{item.current_job_id && <p>当前盘任务：<span className="text-white">#{item.current_job_id}</span></p>}{item.fault_message && <p className="text-orange-200 mt-1">{item.fault_message}</p>}</div>}
      {item.target_type === 'virtual_printer' ? <div className="space-y-2 border-t border-bambu-gray-dark pt-3">
        <label className="block text-xs text-bambu-gray">模拟状态<select aria-label={`${item.name} 状态`} value={state} onChange={event => setState(event.target.value as ProductionPrinterState)} className="mt-1 w-full bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white">{Object.entries(stateLabels).filter(([key]) => key !== 'unknown').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        {(state === 'error' || state === 'maintenance') && <label className="block text-xs text-bambu-gray">故障/维修说明<input value={faultMessage} onChange={event => setFaultMessage(event.target.value)} placeholder="例如：喷嘴需要清洁" className="mt-1 w-full bg-bambu-dark border border-bambu-gray-dark rounded-lg px-3 py-2 text-white" /></label>}
        <Button type="button" size="sm" disabled={heartbeat.isPending} onClick={() => heartbeat.mutate()}><RefreshCw size={14} />发送测试心跳</Button>
        {heartbeat.error && <p className="text-xs text-red-300">{String(heartbeat.error)}</p>}
      </div> : <div className="border-t border-bambu-gray-dark pt-3 text-xs text-bambu-gray">真实打印机状态由 MQTT 自动读取。第14阶段只能从切片库明确选择该机后发送，不能在此页面模拟或改写状态。</div>}
    </CardContent>
  </Card>;
}

export function ProductionPrinterStatusPage() {
  const { data = [], isLoading, refetch, isFetching } = useQuery({ queryKey: ['production-printer-status'], queryFn: productionApi.listPrinterStatuses, refetchInterval: 3000 });
  const available = data.filter(item => item.available_for_allocation).length;
  const unavailable = data.length - available;
  return <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-6">
    <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-200">虚拟打印机可在这里演练状态；真实打印机状态由现有 MQTT 连接自动读取。第14阶段的真实发送只能从切片库明确选择一台打印机并确认后执行。</div>
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-3xl font-bold text-white">打印机状态监控</h1><p className="text-bambu-gray mt-1">系统每 3 秒刷新；心跳超过 {data[0]?.heartbeat_timeout_seconds ?? 30} 秒会自动判定为离线，并停止新的生产分配。</p></div><div className="flex gap-2"><Button type="button" variant="secondary" disabled={isFetching} onClick={() => refetch()}><RefreshCw size={16} />刷新</Button><Link to="/production-orders" className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-bambu-green hover:underline"><Link2 size={16} />生产订单</Link></div></div>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3"><Card><CardContent><p className="text-xs text-bambu-gray">监控目标</p><p className="text-2xl text-white font-semibold mt-1">{data.length}</p></CardContent></Card><Card><CardContent><p className="text-xs text-bambu-gray">可分配</p><p className="text-2xl text-bambu-green font-semibold mt-1">{available}</p></CardContent></Card><Card><CardContent><p className="text-xs text-bambu-gray">不可分配</p><p className="text-2xl text-red-300 font-semibold mt-1">{unavailable}</p></CardContent></Card><Card><CardContent><p className="text-xs text-bambu-gray">自动刷新</p><p className="text-2xl text-white font-semibold mt-1">3 秒</p></CardContent></Card></div>
    {isLoading ? <Card><CardContent className="text-bambu-gray">正在读取打印机状态…</CardContent></Card> : data.length === 0 ? <Card><CardContent className="text-bambu-gray">还没有配置打印机或虚拟打印机。</CardContent></Card> : <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">{data.map(item => <PrinterStatusCard key={item.target_key} item={item} />)}</div>}
    <Card><CardHeader><h2 className="text-lg font-semibold text-white flex items-center gap-2"><Activity size={18} />状态如何影响自动分配</h2></CardHeader><CardContent className="text-sm text-bambu-gray space-y-2"><p>空闲、打印中、暂停、已完成：仍可作为状态来源；离线、故障、维修中：不会被新任务分配。</p><p>已分配但尚未开始的任务，在目标进入不可用状态后会回到待分配，系统下一轮自动寻找其他兼容目标。正在打印的任务不会被后台强制改写。</p><p className="flex items-center gap-1"><Wrench size={14} />第14阶段真实机只允许从切片库单机确认发送。</p></CardContent></Card>
  </div>;
}
