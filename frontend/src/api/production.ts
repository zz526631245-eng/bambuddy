import { getApiBase, getAuthToken, request } from './client';

export interface QuantityLedger {
  planned:number; reserved:number; good:number; scrap:number; remaining:number;
}
export interface PlateJob {
  id:number; requirement_id:number; printer_profile_id?:number|null; virtual_printer_id?:number|null; queue_item_id?:number|null;
  printer_profile_name?:string|null; printer_model?:string|null; assigned_printer_id?:number|null; assigned_printer_name?:string|null; assigned_printer_model?:string|null; virtual_printer_name?:string|null; queue_status?:string|null;
  planned_quantity:number; status:string; workflow_status?:string; machine_result?:'completed'|'failed'|null;
  quality_good_quantity?:number|null; quality_scrap_quantity?:number|null;
  print_started_at?:string|null; print_finished_at?:string|null; quality_confirmed_at?:string|null; cleanup_confirmed_at?:string|null;
  slice_status:string; slice_attempts:number; slice_error?:string|null;
  slice_result?:Record<string,unknown>|null; sliced_at?:string|null; created_at:string; updated_at:string;
  slice_time_review_status?:'not_required'|'pending'|'approved'|'rejected'; slice_time_limit_seconds?:number; max_units_per_plate?:number|null;
}
export interface ProductionRequirement {
  id:number; order_id:number; recipe_id:number; component_id?:number|null; unit_quantity:number;
  required_quantity:number; reserved_quantity:number; good_quantity:number; scrap_quantity:number;
  status:string; component_snapshot?:Record<string,unknown>|null; recipe_snapshot?:Record<string,unknown>|null;
  ledger:QuantityLedger; plate_jobs:PlateJob[]; created_at:string; updated_at:string;
}
export interface ProductionOperation {
  id:number; operation_id:string; operation_type:string; entity_type:string; entity_id?:number|null;
  payload?:Record<string,unknown>|null; created_at:string;
}
export interface ProductionOrder {
  id:number; order_number:string; product_id:number; product_file_snapshot?:Record<string,unknown>|null; quantity:number; priority:number; status:string;
  due_at?:string|null; notes?:string|null; product_snapshot?:Record<string,string|number|null>|null;
  bom_snapshot?:Array<Record<string,unknown>>|null; recipe_snapshot?:Array<Record<string,unknown>>|null;
  created_at:string; updated_at:string; deleted_at?:string|null; completed_at?:string|null;
  priority_label?:string; overdue?:boolean; delivery_status?:'on_track'|'overdue'|'completed'|'cancelled';
  completed_quantity?:number; printing_quantity?:number; assigned_quantity?:number; quality_quantity?:number;
  cleanup_quantity?:number; scrap_quantity?:number; remaining_quantity?:number;
  assigned_printer_names?:string[]; compatible_printer_count?:number; matching_consumable_printer_count?:number;
}
export interface ProductionOrderDetail extends ProductionOrder {
  requirements:ProductionRequirement[]; operations:ProductionOperation[];
}
export interface ProductOrderSummary {
  product_id:number; total_quantity:number; completed_quantity:number; pending_quantity:number;
  product_name?:string|null; product_sku?:string|null; remaining_quantity?:number;
  printing_quantity?:number; assigned_quantity?:number; quality_quantity?:number; cleanup_quantity?:number;
  scrap_quantity?:number; order_count?:number; overdue_order_count?:number; overdue?:boolean;
  highest_priority?:number; priority_label?:string; due_at?:string|null; assigned_printer_names?:string[];
}
export interface SliceArtifact {
  id:number; source_product_file_id:number; source_library_file_id:number; output_library_file_id:number;
  output_file_name?:string|null;
  source_sha256:string; source_version:number; strategy:string; target_printer_preset?:string|null;
  target_printer_model?:string|null; settings_fingerprint:string; arranged_by_slicer:boolean;
  print_time_seconds?:number|null; filament_used_g?:number|null; filament_used_mm?:number|null;
  output_sha256:string; created_at:string; updated_at:string;
}
export interface RealPrinterDispatch {
  operation_id:string; artifact_id:number; plate_job_id?:number|null; queue_item_id:number;
  printer_id:number; printer_name:string; printer_model?:string|null; queue_status:string;
  manual_confirmation:boolean; transport:string; replayed:boolean;
}
export interface PrinterConsumable {
  id:number; printer_id?:number|null; virtual_printer_id?:number|null;
  printer_name?:string|null; virtual_printer_name?:string|null; spool_id?:number|null;
  scan_code:string; material:string; color_hex:string; color_name?:string|null;
  source:string; operation_id:string; is_active:boolean; scanned_at:string; replaced_at?:string|null;
}
export interface PrinterConsumableTarget {
  id:number; name:string; kind:'printer'|'virtual_printer'; model?:string|null; loaded_filaments:Array<Record<string,unknown>>; awaiting_plate_clear?:boolean; is_active?:boolean;
}
export interface ConsumableUnit {
  id:number; material_type_id:number; material_type_code:string; material:string; brand?:string|null;
  color_name?:string|null; color_hex?:string|null; unit_code:string; status:string; label_batch_id:string;
  initial_weight_g?:number|null; unit_price?:number|null; remaining_weight_g?:number|null; storage_location?:string|null; generated_at:string;
  received_at?:string|null; depleted_at?:string|null; scrapped_at?:string|null; replayed?:boolean;
}
export interface ConsumableSummary { generated:number; in_stock:number; bound:number; depleted:number; scrapped:number; total:number; received_total:number; }
export interface ConsumableInventoryGroup {
  brand?:string|null; material:string; subtype?:string|null; color_name?:string|null; color_hex?:string|null;
  generated:number; in_stock:number; bound:number; depleted:number; scrapped:number; total:number; received_total:number;
}
export interface ConsumableBatchHistory {
  batch_id:string; material_type_id:number; material_type_code:string; material:string; subtype?:string|null;
  brand?:string|null; color_name?:string|null; color_hex?:string|null; quantity:number; received_count:number; generated_at:string;
}
export interface ConsumableConsumptionGroup {
  brand?:string|null; material:string; subtype?:string|null; color_name?:string|null; color_hex?:string|null;
  consumed_g:number; cost:number; event_count:number;
}
export interface ConsumableUsageEvent {
  id:number; consumable_unit_id?:number|null; unit_code?:string|null; material_type_code?:string|null;
  brand?:string|null; material?:string|null; subtype?:string|null; color_name?:string|null; color_hex?:string|null;
  queue_item_id?:number|null; plate_job_id?:number|null; printer_id?:number|null;
  consumed_g:number; cost:number; source:string; recorded_at:string;
}
export interface ConsumableConsumptionSummary {
  period:string; start_date:string; end_date:string; consumed_g:number; cost:number; event_count:number;
  groups:ConsumableConsumptionGroup[]; events:ConsumableUsageEvent[];
}
export type ProductionPrinterState = 'unknown'|'idle'|'printing'|'paused'|'finished'|'offline'|'error'|'maintenance';
export interface ProductionPrinterStatus {
  id?:number|null; target_key:string; target_type:'printer'|'virtual_printer'; target_id:number;
  name:string; model?:string|null; state:ProductionPrinterState; effective_state:ProductionPrinterState;
  available_for_allocation:boolean; stale:boolean; source:string; last_heartbeat_at?:string|null;
  observed_at?:string|null; seconds_since_heartbeat?:number|null; current_job_id?:number|null;
  current_job_state?:string|null; fault_code?:string|null; fault_message?:string|null;
  loaded_filaments:Array<Record<string,unknown>>; telemetry:Record<string,unknown>;
  heartbeat_timeout_seconds:number; transport_enabled:boolean; replayed?:boolean;
}
export interface PlateJobPreviewItem {
  requirement_id:number; printer_profile_id?:number|null; planned_quantity:number;
  component_name:string; print_plan_name:string;
}
export interface ProductionOrderAvailability {
  product_id:number; product_file_id:number; compatible_printer_count:number; matching_consumable_printer_count:number;
  available_printer_names:string[]; required_materials:string[]; required_colors:string[];
}

const operationId=(prefix:string)=>`${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;

export const productionApi={
  listOrders:(params?:{history?:boolean;search?:string;from_date?:string;to_date?:string})=>{
    const query = new URLSearchParams();
    if (params?.history) query.set('history','true');
    if (params?.search) query.set('search',params.search);
    if (params?.from_date) query.set('from_date',params.from_date);
    if (params?.to_date) query.set('to_date',params.to_date);
    return request<ProductionOrder[]>('/production/orders' + (query.toString() ? `?${query}` : ''));
  },
  listProductSummaries:(workbench=false, search?:string)=>request<ProductOrderSummary[]>(workbench ? '/production/product-workbench' + (search ? '?search=' + encodeURIComponent(search) : '') : '/production/product-summaries'),
  getOrder:(id:number)=>request<ProductionOrderDetail>(`/production/orders/${id}`),
  createOrder:(data:{order_number?:string;product_id:number;product_file_id?:number|null;quantity:number;priority:number;due_at?:string|null;notes?:string|null})=>
    request<ProductionOrder>('/production/orders',{method:'POST',body:JSON.stringify({...data,operation_id:operationId('create-order')})}),
  updateOrder:(id:number,data:{priority?:number;due_at?:string|null;notes?:string|null})=>
    request<ProductionOrder>(`/production/orders/${id}`,{method:'PATCH',body:JSON.stringify(data)}),
  appendOrderQuantity:(id:number,data:{quantity:number})=>
    request<ProductionOrder>(`/production/orders/${id}/quantity`,{method:'POST',body:JSON.stringify({...data,operation_id:operationId('append-order')})}),
  replanOrder:(id:number,data:{due_at?:string|null;priority?:number})=>
    request<ProductionOrder>(`/production/orders/${id}/replan`,{method:'POST',body:JSON.stringify({...data,operation_id:operationId('replan-order')})}),
  orderAvailability:(productId:number,productFileId:number)=>
    request<ProductionOrderAvailability>(`/production/orders/availability?product_id=${productId}&product_file_id=${productFileId}`),
  changeStatus:(id:number,action:'pause'|'resume')=>
    request<ProductionOrder>(`/production/orders/${id}/status`,{method:'POST',body:JSON.stringify({operation_id:operationId(action),action})}),
  cancelOrder:(id:number)=>
    request<ProductionOrder>(`/production/orders/${id}/cancel`,{method:'POST',body:JSON.stringify({operation_id:operationId('cancel')})}),
  deleteOrder:(id:number)=>request<void>(`/production/orders/${id}`,{method:'DELETE'}),
  previewJobs:(id:number)=>request<{order_id:number;items:PlateJobPreviewItem[]}>(`/production/orders/${id}/plate-jobs/preview`),
  confirmJobs:(id:number,items:PlateJobPreviewItem[])=>
    request<{order_id:number;items:PlateJob[]}>(`/production/orders/${id}/plate-jobs/confirm`,{method:'POST',body:JSON.stringify({operation_id:operationId('confirm-jobs'),items})}),
  retrySlice:(plateJobId:number)=>request<PlateJob>(`/production/plate-jobs/${plateJobId}/slice`,{method:'POST'}),
  cancelPlateJob:(plateJobId:number)=>request<PlateJob>(`/production/plate-jobs/${plateJobId}/cancel`,{method:'POST'}),
  deletePlateJob:(plateJobId:number)=>request<void>(`/production/plate-jobs/${plateJobId}`,{method:'DELETE'}),
  advanceWorkflow:(plateJobId:number,action:'prepare'|'start'|'finish'|'quality'|'cleanup',data?:{machine_result?:'completed'|'failed';good_quantity?:number})=>
    request<PlateJob>(`/production/plate-jobs/${plateJobId}/workflow/${action}`,{method:'POST',body:JSON.stringify({operation_id:operationId(`plate-${action}`),...(data ?? {})})}),
  realSlice:(plateJobId:number,data?:{target_printer_preset?:string;target_printer_model?:string})=>request<PlateJob>(`/production/plate-jobs/${plateJobId}/real-slice`,{method:'POST',body:JSON.stringify(data ?? {})}),
  reviewSliceTime:(plateJobId:number,approve:boolean)=>request<PlateJob>(`/production/plate-jobs/${plateJobId}/slice-time-review`,{method:'POST',body:JSON.stringify({operation_id:operationId('slice-time-review'),approve})}),
  listSliceArtifacts:()=>request<SliceArtifact[]>('/production/slice-artifacts'),
  listPlateJobs:()=>request<PlateJob[]>('/production/plate-jobs'),
  dispatchSliceArtifact:(artifactId:number,data:{printer_id:number;plate_job_id?:number})=>
    request<RealPrinterDispatch>(`/production/slice-artifacts/${artifactId}/dispatch`,{method:'POST',body:JSON.stringify({operation_id:operationId('stage14-dispatch'),confirm:true,...data})}),
  listConsumables:()=>request<PrinterConsumable[]>('/production/printer-consumables'),
  listConsumableTargets:()=>request<PrinterConsumableTarget[]>('/production/printer-consumables/targets'),
  clearPlate:(printerId:number)=>request<{success:boolean;message:string}>(`/printers/${printerId}/clear-plate`,{method:'POST'}),
  setPrinterMaintenance:(printerId:number,maintenance:boolean)=>request<{id:number;name:string;is_active:boolean}>(`/printers/${printerId}/maintenance`,{method:'POST',body:JSON.stringify({maintenance})}),
  scanConsumable:(data:{operation_id:string;scan_code:string;material?:string|null;color_hex?:string|null;color_name?:string|null;spool_id?:number|null;consumable_unit_id?:number|null;printer_id?:number|null;virtual_printer_id?:number|null})=>
    request<PrinterConsumable & { replayed:boolean; replaced_id?:number|null }>('/production/printer-consumables/scan',{method:'POST',body:JSON.stringify(data)}),
  listConsumableUnits:(status?:string)=>request<ConsumableUnit[]>('/production/consumable-library?' + (status ? 'status_filter=' + encodeURIComponent(status) + '&' : '') + 'include_pending=false'),
  consumableSummary:()=>request<ConsumableSummary>('/production/consumable-library/summary?include_pending=false'),
  consumableInventorySummary:()=>request<ConsumableInventoryGroup[]>('/production/consumable-library/inventory-summary?include_pending=false'),
  consumableConsumptionSummary:(params?:{period?:string;start_date?:string;end_date?:string})=>{
    const query = new URLSearchParams();
    if (params?.period) query.set('period', params.period);
    if (params?.start_date) query.set('start_date', params.start_date);
    if (params?.end_date) query.set('end_date', params.end_date);
    return request<ConsumableConsumptionSummary>('/production/consumable-library/consumption-summary' + (query.toString() ? '?' + query.toString() : ''));
  },
  generateConsumableBatch:(data:{operation_id:string;material_type_id:number;quantity:number;initial_weight_g?:number|null;unit_price?:number|null;remaining_weight_g?:number|null})=>
    request<{batch_id:string;items:ConsumableUnit[]}>('/production/consumable-library/batches',{method:'POST',body:JSON.stringify(data)}),
  listConsumableBatchHistory:()=>request<ConsumableBatchHistory[]>('/production/consumable-library/batches'),
  downloadConsumableBatchPdf:async (batchId:string):Promise<void> => {
    const headers:Record<string,string> = {};
    const token = getAuthToken(); if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${getApiBase()}/production/consumable-library/batches/${encodeURIComponent(batchId)}/pdf`, { headers });
    if (!response.ok) throw new Error(`二维码 PDF 下载失败（${response.status}）`);
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)/i);
    const filename = filenameMatch?.[1] ? decodeURIComponent(filenameMatch[1]) : `consumable-qr-${batchId}.pdf`;
    const url = window.URL.createObjectURL(blob); const anchor = document.createElement('a');
    anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.URL.revokeObjectURL(url);
  },
  scanConsumableUnit:(data:{operation_id:string;unit_code:string;action:string;remaining_weight_g?:number;storage_location?:string|null})=>
    request<ConsumableUnit>('/production/consumable-library/scan',{method:'POST',body:JSON.stringify(data)}),
  listPrinterStatuses:()=>request<ProductionPrinterStatus[]>('/production/printer-status'),
  heartbeatPrinter:(data:{operation_id:string;target_type:'printer'|'virtual_printer';target_id:number;state:ProductionPrinterState;source?:'stage13_simulation'|'adapter';current_job_id?:number|null;current_job_state?:string|null;fault_code?:string|null;fault_message?:string|null;loaded_filaments?:Array<Record<string,unknown>>;telemetry?:Record<string,unknown>})=>
    request<ProductionPrinterStatus>('/production/printer-status/heartbeat',{method:'POST',body:JSON.stringify(data)}),
  downloadSliceArtifact: async (artifactId:number):Promise<void> => {
    const headers:Record<string,string> = {};
    const token = getAuthToken(); if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${getApiBase()}/production/slice-artifacts/${artifactId}/download`, { headers });
    if (!response.ok) throw new Error(`下载切片文件失败（${response.status}）`);
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob); const anchor = document.createElement('a');
    anchor.href = url; anchor.download = response.headers.get('content-disposition')?.match(/filename="?([^";]+)"?/)?.[1] ?? `slice_${artifactId}.gcode.3mf`;
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.URL.revokeObjectURL(url);
  },
};
