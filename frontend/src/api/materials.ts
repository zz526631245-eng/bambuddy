import { request } from './client';
import type { ConsumableUnit } from './production';
export interface MaterialConsumableStats {
  generated:number; in_stock:number; bound:number; depleted:number; scrapped:number; received:number; total:number;
  units:ConsumableUnit[];
}
export interface MaterialType { id:number; code:string; material:string; subtype?:string|null; brand?:string|null; color_name?:string|null; color_hex?:string|null; is_active:boolean; consumable_stats?:MaterialConsumableStats }
export type MaterialInput = Omit<MaterialType,'id'>;
export const materialsApi={
 list:()=>request<MaterialType[]>('/production/material-types'),
 create:(data:MaterialInput)=>request<MaterialType>('/production/material-types',{method:'POST',body:JSON.stringify(data)}),
 update:(id:number,data:MaterialInput)=>request<MaterialType>(`/production/material-types/${id}`,{method:'PUT',body:JSON.stringify(data)}),
 remove:(id:number)=>request<void>(`/production/material-types/${id}`,{method:'DELETE'}),
 mapSpool:(id:number,spoolId:number)=>request<void>(`/production/material-types/${id}/spools/${spoolId}`,{method:'PUT'}),
};
