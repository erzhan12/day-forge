import { type ApiResult, requestJson } from "./useHttp"
import type { Template, TemplateBlock } from "../types"

export interface TemplatePayload {
  name: string
  type: "weekday" | "weekend"
  blocks: TemplateBlock[]
}

export interface TemplateResult extends ApiResult {
  template?: Template
}

export interface TemplatesListResult extends ApiResult {
  templates?: Template[]
}

function asTemplate(raw: unknown): Template | undefined {
  if (!raw || typeof raw !== "object") return undefined
  return raw as Template
}

export function useTemplates() {
  async function listTemplates(): Promise<TemplatesListResult> {
    const result = await requestJson("/api/templates/", "GET")
    if (result.ok) {
      const list = (result.data?.templates as Template[]) ?? []
      return { ok: true, status: result.status, data: result.data, templates: list }
    }
    return result
  }

  async function createTemplate(
    payload: TemplatePayload,
  ): Promise<TemplateResult> {
    const result = await requestJson(
      "/api/templates/",
      "POST",
      payload as unknown as Record<string, unknown>,
    )
    if (result.ok) {
      return {
        ok: true,
        status: result.status,
        data: result.data,
        template: asTemplate(result.data),
      }
    }
    return result
  }

  async function saveTemplate(
    id: number,
    payload: TemplatePayload,
  ): Promise<TemplateResult> {
    const result = await requestJson(
      `/api/templates/${id}/`,
      "PUT",
      payload as unknown as Record<string, unknown>,
    )
    if (result.ok) {
      return {
        ok: true,
        status: result.status,
        data: result.data,
        template: asTemplate(result.data),
      }
    }
    return result
  }

  async function deleteTemplate(id: number): Promise<ApiResult> {
    return await requestJson(`/api/templates/${id}/`, "DELETE")
  }

  return { listTemplates, createTemplate, saveTemplate, deleteTemplate }
}
