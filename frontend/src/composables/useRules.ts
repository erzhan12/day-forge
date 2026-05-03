import { type ApiResult, requestJson } from "./useHttp"
import type { Rule } from "../types"

export interface RuleCreatePayload {
  text: string
  is_active?: boolean
  priority?: number
}

export interface RulePatchPayload {
  text?: string
  is_active?: boolean
  priority?: number
}

export interface RuleResult extends ApiResult {
  rule?: Rule
}

export interface RulesListResult extends ApiResult {
  rules?: Rule[]
}

function asRule(raw: unknown): Rule | undefined {
  if (!raw || typeof raw !== "object") return undefined
  return raw as Rule
}

export function useRules() {
  async function listRules(): Promise<RulesListResult> {
    const result = await requestJson("/api/rules/", "GET")
    if (result.ok) {
      const list = (result.data?.rules as Rule[]) ?? []
      return { ok: true, status: result.status, data: result.data, rules: list }
    }
    return result
  }

  async function createRule(payload: RuleCreatePayload): Promise<RuleResult> {
    const result = await requestJson(
      "/api/rules/",
      "POST",
      payload as unknown as Record<string, unknown>,
    )
    if (result.ok) {
      return {
        ok: true,
        status: result.status,
        data: result.data,
        rule: asRule(result.data),
      }
    }
    return result
  }

  async function updateRule(
    id: number,
    payload: RulePatchPayload,
  ): Promise<RuleResult> {
    const result = await requestJson(
      `/api/rules/${id}/`,
      "PATCH",
      payload as unknown as Record<string, unknown>,
    )
    if (result.ok) {
      return {
        ok: true,
        status: result.status,
        data: result.data,
        rule: asRule(result.data),
      }
    }
    return result
  }

  async function deleteRule(id: number): Promise<ApiResult> {
    return await requestJson(`/api/rules/${id}/`, "DELETE")
  }

  return { listRules, createRule, updateRule, deleteRule }
}
