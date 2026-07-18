import { request } from './client';

export interface QuantityLedger {
  planned:number; reserved:number; good:number; scrap:number; remaining:number;
}
export interface PlateJob {
  id:number; requirement_id:number; printer_profile_id?:number|null; queue_item_id?:number|null;
  planned_quantity:number; status:string; created_at:string; updated_at:string;
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
  id:number; order_number:string; product_id:number; quantity:number; priority:number; status:string;
  due_at?:string|null; notes?:string|null; product_snapshot?:Record<string,unknown>|null;
  bom_snapshot?:Array<Record<string,unknown>>|null; recipe_snapshot?:Array<Record<string,unknown>>|null;
  created_at:string; updated_at:string;
}
export interface ProductionOrderDetail extends ProductionOrder {
  requirements:ProductionRequirement[]; operations:ProductionOperation[];
}
export interface PlateJobPreviewItem {
  requirement_id:number; printer_profile_id?:number|null; planned_quantity:number;
  component_name:string; print_plan_name:string;
}

const operationId=(prefix:string)=>`${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;

export const productionApi={
  listOrders:()=>request<ProductionOrder[]>('/production/orders'),
  getOrder:(id:number)=>request<ProductionOrderDetail>(`/production/orders/${id}`),
  createOrder:(data:{order_number:string;product_id:number;quantity:number;priority:number;due_at?:string|null;notes?:string|null})=>
    request<ProductionOrder>('/production/orders',{method:'POST',body:JSON.stringify({...data,operation_id:operationId('create-order')})}),
  updateOrder:(id:number,data:{priority?:number;due_at?:string|null;notes?:string|null})=>
    request<ProductionOrder>(`/production/orders/${id}`,{method:'PATCH',body:JSON.stringify(data)}),
  changeStatus:(id:number,action:'pause'|'resume')=>
    request<ProductionOrder>(`/production/orders/${id}/status`,{method:'POST',body:JSON.stringify({operation_id:operationId(action),action})}),
  cancelOrder:(id:number)=>
    request<ProductionOrder>(`/production/orders/${id}/cancel`,{method:'POST',body:JSON.stringify({operation_id:operationId('cancel')})}),
  previewJobs:(id:number)=>request<{order_id:number;items:PlateJobPreviewItem[]}>(`/production/orders/${id}/plate-jobs/preview`),
  confirmJobs:(id:number,items:PlateJobPreviewItem[])=>
    request<{order_id:number;items:PlateJob[]}>(`/production/orders/${id}/plate-jobs/confirm`,{method:'POST',body:JSON.stringify({operation_id:operationId('confirm-jobs'),items})}),
};
