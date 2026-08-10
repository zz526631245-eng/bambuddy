import { getAuthToken, request } from './client';

export interface QuantityLedger {
  planned:number; reserved:number; good:number; scrap:number; remaining:number;
}
export interface PlateJob {
  id:number; requirement_id:number; printer_profile_id?:number|null; virtual_printer_id?:number|null; queue_item_id?:number|null;
  printer_profile_name?:string|null; printer_model?:string|null; virtual_printer_name?:string|null; queue_status?:string|null;
  planned_quantity:number; status:string; workflow_status?:string; machine_result?:'completed'|'failed'|null;
  quality_good_quantity?:number|null; quality_scrap_quantity?:number|null;
  print_started_at?:string|null; print_finished_at?:string|null; quality_confirmed_at?:string|null; cleanup_confirmed_at?:string|null;
  slice_status:string; slice_attempts:number; slice_error?:string|null;
  slice_result?:Record<string,unknown>|null; sliced_at?:string|null; created_at:string; updated_at:string;
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
  due_at?:string|null; notes?:string|null; product_snapshot?:Record<string,unknown>|null;
  bom_snapshot?:Array<Record<string,unknown>>|null; recipe_snapshot?:Array<Record<string,unknown>>|null;
  created_at:string; updated_at:string;
}
export interface ProductionOrderDetail extends ProductionOrder {
  requirements:ProductionRequirement[]; operations:ProductionOperation[];
}
export interface ProductOrderSummary {
  product_id:number; total_quantity:number; completed_quantity:number; pending_quantity:number;
}
export interface SliceArtifact {
  id:number; source_product_file_id:number; source_library_file_id:number; output_library_file_id:number;
  output_file_name?:string|null;
  source_sha256:string; source_version:number; strategy:string; target_printer_preset?:string|null;
  target_printer_model?:string|null; settings_fingerprint:string; arranged_by_slicer:boolean;
  print_time_seconds?:number|null; filament_used_g?:number|null; filament_used_mm?:number|null;
  output_sha256:string; created_at:string; updated_at:string;
}
export interface PrinterConsumable {
  id:number; printer_id?:number|null; virtual_printer_id?:number|null;
  printer_name?:string|null; virtual_printer_name?:string|null; spool_id?:number|null;
  scan_code:string; material:string; color_hex:string; color_name?:string|null;
  source:string; operation_id:string; is_active:boolean; scanned_at:string; replaced_at?:string|null;
}
export interface PrinterConsumableTarget {
  id:number; name:string; kind:'printer'|'virtual_printer'; model?:string|null; loaded_filaments:Array<Record<string,unknown>>;
}
export interface PlateJobPreviewItem {
  requirement_id:number; printer_profile_id?:number|null; planned_quantity:number;
  component_name:string; print_plan_name:string;
}

const operationId=(prefix:string)=>`${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;

export const productionApi={
  listOrders:()=>request<ProductionOrder[]>('/production/orders'),
  listProductSummaries:()=>request<ProductOrderSummary[]>('/production/product-summaries'),
  getOrder:(id:number)=>request<ProductionOrderDetail>(`/production/orders/${id}`),
  createOrder:(data:{order_number?:string;product_id:number;product_file_id?:number|null;quantity:number;priority:number;due_at?:string|null;notes?:string|null})=>
    request<ProductionOrder>('/production/orders',{method:'POST',body:JSON.stringify({...data,operation_id:operationId('create-order')})}),
  updateOrder:(id:number,data:{priority?:number;due_at?:string|null;notes?:string|null})=>
    request<ProductionOrder>(`/production/orders/${id}`,{method:'PATCH',body:JSON.stringify(data)}),
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
  listSliceArtifacts:()=>request<SliceArtifact[]>('/production/slice-artifacts'),
  listConsumables:()=>request<PrinterConsumable[]>('/production/printer-consumables'),
  listConsumableTargets:()=>request<PrinterConsumableTarget[]>('/production/printer-consumables/targets'),
  scanConsumable:(data:{operation_id:string;scan_code:string;material:string;color_hex:string;color_name?:string|null;spool_id?:number|null;printer_id?:number|null;virtual_printer_id?:number|null})=>
    request<PrinterConsumable & { replayed:boolean; replaced_id?:number|null }>('/production/printer-consumables/scan',{method:'POST',body:JSON.stringify(data)}),
  downloadSliceArtifact: async (artifactId:number):Promise<void> => {
    const headers:Record<string,string> = {};
    const token = getAuthToken(); if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`/api/v1/production/slice-artifacts/${artifactId}/download`, { headers });
    if (!response.ok) throw new Error(`下载切片文件失败（${response.status}）`);
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob); const anchor = document.createElement('a');
    anchor.href = url; anchor.download = response.headers.get('content-disposition')?.match(/filename="?([^";]+)"?/)?.[1] ?? `slice_${artifactId}.gcode.3mf`;
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.URL.revokeObjectURL(url);
  },
};
