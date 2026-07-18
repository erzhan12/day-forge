import { type ApiResult, requestJson } from "./useHttp"
import type { TravelRule } from "../types"

export interface TravelRuleCreatePayload {
  keyword: string
  travel_there_minutes?: number
  travel_back_minutes?: number
  category?: TravelRule["category"]
  order?: number
}

export interface TravelRulePatchPayload {
  keyword?: string
  travel_there_minutes?: number
  travel_back_minutes?: number
  category?: TravelRule["category"]
  order?: number
}

export interface TravelRuleResult extends ApiResult {
  rule?: TravelRule
}

export interface TravelRulesListResult extends ApiResult {
  rules?: TravelRule[]
}

function asTravelRule(raw: unknown): TravelRule | undefined {
  if (!raw || typeof raw !== "object") return undefined
  return raw as TravelRule
}

export function useTravelRules() {
  async function listRules(): Promise<TravelRulesListResult> {
    const result = await requestJson("/api/calendar/travel-rules/", "GET")
    if (result.ok) {
      const list = (result.data?.travel_rules as TravelRule[]) ?? []
      return { ok: true, status: result.status, data: result.data, rules: list }
    }
    return result
  }

  async function createRule(
    payload: TravelRuleCreatePayload,
  ): Promise<TravelRuleResult> {
    const result = await requestJson(
      "/api/calendar/travel-rules/",
      "POST",
      payload as unknown as Record<string, unknown>,
    )
    if (result.ok) {
      return {
        ok: true,
        status: result.status,
        data: result.data,
        rule: asTravelRule(result.data),
      }
    }
    return result
  }

  async function updateRule(
    id: number,
    payload: TravelRulePatchPayload,
  ): Promise<TravelRuleResult> {
    const result = await requestJson(
      `/api/calendar/travel-rules/${id}/`,
      "PATCH",
      payload as unknown as Record<string, unknown>,
    )
    if (result.ok) {
      return {
        ok: true,
        status: result.status,
        data: result.data,
        rule: asTravelRule(result.data),
      }
    }
    return result
  }

  async function deleteRule(id: number): Promise<ApiResult> {
    return await requestJson(`/api/calendar/travel-rules/${id}/`, "DELETE")
  }

  return { listRules, createRule, updateRule, deleteRule }
}
